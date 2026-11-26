"""
네이버 공식 API 클라이언트

1) 네이버 검색광고 API (keywordstool)
   - 월간 PC/모바일 검색량, 클릭수, 클릭률, 광고 경쟁정도, 연관 키워드
   - 발급: https://searchad.naver.com → 도구 → API 사용 관리
2) 네이버 검색 API (블로그/카페 검색)
   - 블로그/카페 누적 문서 수, 최근 발행 글 날짜
   - 발급: 네이버 클라우드 플랫폼 콘솔 → NAVER API HUB → Application 등록
     (2026-07-31부터 개발자센터 신규 발급 중단. 기존 개발자센터 키도 provider="developers"로 사용 가능)
3) 검색어 트렌드 API - 선택 (같은 Application 에 추가)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import date, datetime, timedelta

import requests

TIMEOUT = 15


def _to_int(value) -> int:
    """검색광고 API는 검색량이 적으면 '< 10' 문자열을 준다 → 5로 간주."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        v = value.replace(",", "").strip()
        if v.startswith("<"):
            return 5
        try:
            return int(float(v))
        except ValueError:
            return 0
    return 0


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 1. 검색광고 API
# ---------------------------------------------------------------------------
class SearchAdClient:
    BASE_URL = "https://api.searchad.naver.com"

    def __init__(self, api_key: str, secret_key: str, customer_id: str, session=None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.customer_id = str(customer_id)
        self.session = session or requests.Session()

    def _headers(self, method: str, uri: str) -> dict:
        ts = str(int(time.time() * 1000))
        message = f"{ts}.{method}.{uri}"
        sig = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).digest()
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": ts,
            "X-API-KEY": self.api_key,
            "X-Customer": self.customer_id,
            "X-Signature": base64.b64encode(sig).decode(),
        }

    def keyword_tool(self, hint_keywords: list[str]) -> list[dict]:
        """힌트 키워드(최대 5개)로 연관 키워드 + 월간 검색량 조회."""
        uri = "/keywordstool"
        # 검색광고 API는 키워드 안의 공백을 허용하지 않음
        hints = [k.replace(" ", "") for k in hint_keywords if k.strip()][:5]
        params = {"hintKeywords": ",".join(hints), "showDetail": "1"}
        for attempt in range(4):
            r = self.session.get(
                self.BASE_URL + uri, params=params, headers=self._headers("GET", uri), timeout=TIMEOUT
            )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(1.0 * (attempt + 1))
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"검색광고 API 오류 {r.status_code}: {r.text[:300]}")
        rows = []
        for item in r.json().get("keywordList", []):
            pc = _to_int(item.get("monthlyPcQcCnt"))
            mo = _to_int(item.get("monthlyMobileQcCnt"))
            rows.append(
                {
                    "키워드": item.get("relKeyword", ""),
                    "PC 검색량": pc,
                    "모바일 검색량": mo,
                    "월간 검색량": pc + mo,
                    "PC 클릭수": _to_float(item.get("monthlyAvePcClkCnt")),
                    "모바일 클릭수": _to_float(item.get("monthlyAveMobileClkCnt")),
                    "PC 클릭률(%)": _to_float(item.get("monthlyAvePcCtr")),
                    "모바일 클릭률(%)": _to_float(item.get("monthlyAveMobileCtr")),
                    "광고 노출수": _to_float(item.get("plAvgDepth")),
                    "광고 경쟁": item.get("compIdx", ""),
                }
            )
        return rows


# ---------------------------------------------------------------------------
# 2. 검색 API (블로그 / 카페)
# ---------------------------------------------------------------------------
class OpenApiClient:
    """
    provider="apihub"     : NAVER API HUB (네이버 클라우드 플랫폼) — 2026-07-31 이후 신규 발급은 여기서만 가능
    provider="developers" : 기존 네이버 개발자센터 키 (2027-06-30까지 동작)
    """

    ENDPOINTS = {
        "apihub": {
            "base": "https://naverapihub.apigw.ntruss.com",
            "blog": "/search/v1/blog",
            "cafearticle": "/search/v1/cafearticle",
            "trend": "/search-trend/v1/search",
            "id_header": "X-NCP-APIGW-API-KEY-ID",
            "secret_header": "X-NCP-APIGW-API-KEY",
        },
        "developers": {
            "base": "https://openapi.naver.com",
            "blog": "/v1/search/blog.json",
            "cafearticle": "/v1/search/cafearticle.json",
            "trend": "/v1/datalab/search",
            "id_header": "X-Naver-Client-Id",
            "secret_header": "X-Naver-Client-Secret",
        },
    }

    def __init__(self, client_id: str, client_secret: str, provider: str = "apihub", session=None):
        self.session = session or requests.Session()
        self.ep = self.ENDPOINTS.get(provider, self.ENDPOINTS["apihub"])
        self.headers = {
            self.ep["id_header"]: client_id.strip(),
            self.ep["secret_header"]: client_secret.strip(),
        }

    def _search(self, kind: str, query: str, display=1, start=1, sort="sim") -> dict:
        # 너무 빨리 부르면(429) 또는 일시 오류(5xx)면 잠깐 쉬었다가 최대 4번 다시 시도
        for attempt in range(5):
            try:
                r = self.session.get(
                    self.ep["base"] + self.ep[kind],
                    params={"query": query, "display": display, "start": start, "sort": sort},
                    headers=self.headers,
                    timeout=TIMEOUT,
                )
            except requests.RequestException as e:
                if attempt == 4:
                    raise RuntimeError(f"검색 API 연결 오류: {e}")
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise RuntimeError(f"검색 API 오류 {r.status_code}: {r.text[:300]}")

    def blog_total(self, query: str) -> int:
        return int(self._search("blog", query).get("total", 0))

    def cafe_total(self, query: str) -> int:
        return int(self._search("cafearticle", query).get("total", 0))

    def blog_recent_count(self, query: str, days: int = 30, max_pages: int = 10) -> tuple[int, bool]:
        """
        최근 N일 블로그 발행량.
        날짜순 100개씩 최대 1,000개까지 확인한다(API 한도).
        1,000개가 모두 N일 이내면 발행 속도로 추정하고 is_estimate=True 를 돌려준다.
        """
        cutoff = date.today() - timedelta(days=days)
        count = 0
        oldest = None
        for page in range(max_pages):
            data = self._search("blog", query, display=100, start=page * 100 + 1, sort="date")
            items = data.get("items", [])
            if not items:
                return count, False
            for it in items:
                try:
                    d = datetime.strptime(it.get("postdate", ""), "%Y%m%d").date()
                except ValueError:
                    continue
                if d < cutoff:
                    return count, False
                count += 1
                oldest = d
            if len(items) < 100:
                return count, False
        # 1,000개를 다 봤는데도 N일 이내 → 발행 속도로 환산 (경과 시간을 소수 일 단위로)
        if oldest is None:
            return count, False
        elapsed = (datetime.now() - datetime.combine(oldest, datetime.min.time())).total_seconds() / 86400
        return int(count * days / max(elapsed, 0.25)), True

    def datalab_trend(self, keyword: str, months: int = 12, start: date | None = None,
                      end: date | None = None, unit: str = "month") -> list[dict]:
        """상대 검색량 추이(기간 내 최대값=100). unit: date | week | month"""
        end = end or date.today()
        start = start or (end - timedelta(days=months * 31))
        body = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "timeUnit": unit,
            "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}],
        }
        r = self.session.post(
            self.ep["base"] + self.ep["trend"],
            json=body,
            headers={**self.headers, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            raise RuntimeError(f"검색어 트렌드 API 오류 {r.status_code}: {r.text[:300]}")
        results = r.json().get("results", [])
        return results[0].get("data", []) if results else []
