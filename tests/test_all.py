"""
가짜(모의) 네이버 응답으로 핵심 로직을 점검하는 테스트. 실제 API 를 쓰지 않는다.

실행:  python tests/test_all.py      (모두 통과하면 '✅ 전부 통과' 출력)
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd  # noqa: E402

import analyzer  # noqa: E402
import naver_api  # noqa: E402
from naver_api import OpenApiClient, SearchAdClient  # noqa: E402
from region import extract_neighborhoods, keyword_forms, parse_region  # noqa: E402

# 테스트에서는 기다리지 않는다
naver_api.time.sleep = lambda *_: None
analyzer.time.sleep = lambda *_: None


# ---------------------------------------------------------------- 가짜 응답
class R:
    def __init__(self, j, code=200):
        self.j, self.status_code, self.text = j, code, "err"

    def json(self):
        return self.j


def kw_row(k, pc, mo):
    return {"relKeyword": k, "monthlyPcQcCnt": pc, "monthlyMobileQcCnt": mo, "monthlyAvePcClkCnt": 1,
            "monthlyAveMobileClkCnt": 1, "monthlyAvePcCtr": 1, "monthlyAveMobileCtr": 1, "plAvgDepth": 5,
            "compIdx": "중간"}


class FakeNaver:
    """검색광고(keywordstool) + 블로그/카페 검색을 흉내 낸다."""

    def __init__(self, volumes, related, blog_total, cafe_total=None, recent=None):
        self.volumes, self.related = volumes, related
        self.blog_total_fn = blog_total
        self.cafe_total_fn = cafe_total or (lambda q: blog_total(q) // 2)
        self.recent = recent or {}

    def get(self, url, params=None, headers=None, timeout=None):
        if "keywordstool" in url:
            assert " " not in params["hintKeywords"], "검색광고 API 는 공백을 허용하지 않음"
            ks = []
            for h in params["hintKeywords"].split(","):
                ks += self.related.get(h, [h] if h in self.volumes else [])
            return R({"keywordList": [kw_row(k, *self.volumes[k]) for k in dict.fromkeys(ks)]})
        q = params["query"]
        if params.get("sort") == "date":  # 최근 글: 하루 n개씩
            per_day = self.recent.get(q, 0)
            if per_day == 0:
                return R({"total": 0, "items": []})
            start = params["start"]
            today = date.today().toordinal()
            items = [{"postdate": date.fromordinal(today - (start - 1 + i) // per_day).strftime("%Y%m%d")}
                     for i in range(100)]
            return R({"total": 999999, "items": items})
        total = self.cafe_total_fn(q) if "cafe" in url else self.blog_total_fn(q)
        return R({"total": total, "items": []})


# ---------------------------------------------------------------- 테스트들
def test_region_parse():
    cases = {
        "대구 동구 맛집": ("대구", "동구", "맛집"),
        "대구동구맛집": ("대구", "동구", "맛집"),
        "수성구 카페": ("대구", "수성구", "카페"),
        "포항 맛집": ("경북", "포항시", "맛집"),
        "부산 해운대 맛집": ("부산", "해운대구", "맛집"),
    }
    for q, (sd, gu, cat) in cases.items():
        r = parse_region(q)
        assert r and (r["sido"], r["gu"], r["category"]) == (sd, gu, cat), (q, r)
    assert parse_region("팔공산 맛집") is None  # 행정구역이 없으면 None → 블로그 언급으로 추정
    assert keyword_forms("대구", "수성구", "맛집")[0] == "대구수성구맛집"


def test_neighborhood_extract():
    r = parse_region("대구 동구 맛집")
    kws = ["동촌맛집", "대구율하맛집", "부산맛집", "수성구맛집", "대구동구고기맛집", "주변맛집", "해운대맛집", "진천동맛집"]
    names = [n for n, _ in extract_neighborhoods(r, kws)]
    assert "동촌" in names and "율하" in names and "진천동" in names
    for bad in ["부산", "수성구", "고기", "주변", "해운대"]:
        assert bad not in names, bad


def test_variants():
    v = analyzer.variant_keywords("팔공산", "맛집")
    for k in ["팔공산근처맛집", "팔공산주변맛집", "팔공산밥집", "팔공산식당", "팔공산맛집추천"]:
        assert k in v, k
    assert "팔공산맛집" not in v  # 검색어 자체는 제외


def test_monthly_enrichment_matches_blackkiwi():
    """팔공산갓바위: 월 블로그 700, 누적 56,173 → 블랙키위(700/160/860, 1.78%)와 비슷해야 한다."""
    class A:
        def blog_total(self, k): return 56173
        def cafe_total(self, k): return 12000
        def blog_recent_count(self, k): return 700, False
    df = pd.DataFrame([{"키워드": "팔공산갓바위", "PC 검색량": 4020, "모바일 검색량": 35200, "월간 검색량": 39220,
                        "PC 클릭수": 0, "모바일 클릭수": 0}])
    out = analyzer.enrich_with_documents(A(), df).iloc[0]
    assert out["월 블로그 발행"] == 700
    assert 140 <= out["월 카페 발행"] <= 170
    assert abs(out["블로그 포화(%)"] - 1.78) < 0.01
    assert "매우 낮음" in out["경쟁도"]


def test_estimate_caps():
    """날짜순 검색이 누적보다 크게 나와도 카페 추정이 폭주하지 않아야 한다."""
    class A:
        def blog_total(self, k): return 5000
        def cafe_total(self, k): return 400000
        def blog_recent_count(self, k): return 16000, True
    df = pd.DataFrame([{"키워드": "x", "PC 검색량": 1, "모바일 검색량": 1, "월간 검색량": 1000,
                        "PC 클릭수": 0, "모바일 클릭수": 0}])
    out = analyzer.enrich_with_documents(A(), df).iloc[0]
    assert out["월 블로그 발행"] <= 5000
    assert out["월 카페 발행"] <= 400000 * 0.2


def test_retry_and_failure():
    calls = {"flaky": 0}

    class S:
        def get(self, url, params=None, headers=None, timeout=None):
            q = params["query"]
            if q == "bad":
                return R({}, 429)
            if q == "flaky":
                calls["flaky"] += 1
                if calls["flaky"] < 3:
                    return R({}, 429)
            return R({"total": 500, "items": []})
    api = OpenApiClient("i", "c", session=S())
    df = pd.DataFrame([{"키워드": k, "PC 검색량": 1, "모바일 검색량": 1, "월간 검색량": 1000,
                        "PC 클릭수": 0, "모바일 클릭수": 0} for k in ["ok", "bad", "flaky"]])
    out = analyzer.enrich_with_documents(api, df).set_index("키워드")
    assert pd.isna(out.loc["ok", "오류"]) and pd.isna(out.loc["flaky", "오류"])
    assert "429" in out.loc["bad", "오류"]


def test_discover_finds_variants():
    vol = {"팔공산맛집": (1000, 9000), "팔공산카페": (800, 7000), "대구맛집": (20000, 90000), "팔공산": (5000, 30000),
           "팔공산근처맛집": (200, 1500), "팔공산밥집": (40, 300), "팔공산오리고기": (300, 2500)}
    rel = {"팔공산맛집": ["팔공산맛집", "팔공산카페", "대구맛집", "팔공산", "팔공산오리고기"]}
    s = FakeNaver(vol, rel, blog_total=lambda q: 20000, recent={k: 5 for k in vol})
    df, info = analyzer.discover(SearchAdClient("k", "s", "1", session=s), OpenApiClient("i", "c", session=s),
                                 "팔공산 맛집", match="first", min_volume=100)
    found = dict(info["variants"])
    assert "팔공산근처맛집" in found and "팔공산밥집" in found
    assert "대구맛집" not in set(df["키워드"])  # 주제어(팔공산) 없는 키워드는 제외
    assert (df.loc[df["키워드"] == "팔공산근처맛집", "출처"] == "비슷한 표현").all()


def test_region_verification():
    """'대구 동구 X' 가 다른 구보다 많이 언급될 때만 동구 동네로 인정."""
    home = {"동촌": "동구", "율하": "동구", "동성로": "중구", "마산": None}
    vol = {"대구동구맛집": (2000, 9000), "동촌맛집": (800, 6000), "율하맛집": (500, 4000),
           "동성로맛집": (8000, 30000), "마산맛집": (5000, 20000)}
    for g in ["중구", "서구", "남구", "북구", "수성구", "달서구"]:
        vol[f"대구{g}맛집"] = (500, 2000)
    rel = {"대구동구맛집": ["대구동구맛집", "동촌맛집", "율하맛집", "동성로맛집", "마산맛집"]}

    def blog_total(q):
        parts = q.split()
        name = parts[-1]
        h = home.get(name, "동구")
        if len(parts) == 1:
            return 100000
        if len(parts) == 2:
            return 60000 if h else 1000
        return 20000 if parts[1] == h else 3000
    s = FakeNaver(vol, rel, blog_total=blog_total)
    out = analyzer.discover_region(SearchAdClient("k", "s", "1", session=s), OpenApiClient("i", "c", session=s),
                                   "대구 동구 맛집", count_recent=False)
    hoods = set(out["df"].loc[out["df"]["구분"] == "동네·명소", "지역"])
    assert {"동촌", "율하"} <= hoods, hoods
    assert "동성로" not in hoods and "마산" not in hoods
    assert "동성로" in out["rejected"]


def test_scoring():
    good = analyzer.recommend_score(39220, 2.19, True)
    bad = analyzer.recommend_score(39220, 300, True)
    tiny = analyzer.recommend_score(30, 2.19, True)
    assert good > bad and good > tiny


def test_storage_rows():
    import tempfile
    import config
    import storage
    df = pd.DataFrame([{"키워드": "팔공산맛집", "월간 검색량": 1200, "월 전체 발행": 30, "포화지수(%)": 2.5,
                        "경쟁도": "🟢 매우 낮음", "추천점수": 81, "지역": "대구 동구", "PC 검색량": float("nan")}])
    rows = storage.rows_from_table("지역 키워드", "팔공산 맛집", df)
    assert rows[0]["monthly_volume"] == 1200 and rows[0]["score"] == 81 and rows[0]["region"] == "대구 동구"
    assert rows[0]["data"]["PC 검색량"] is None  # NaN 은 비워서 보낸다
    assert storage.rows_from_table("황금 키워드", "x", pd.DataFrame()) == []
    assert storage.save({}, rows) is False  # 주소·키가 없으면 아무것도 안 한다
    # 화면의 '키 저장'이 .env 의 SUPABASE 줄을 지우면 안 된다
    with tempfile.TemporaryDirectory() as d:
        env = os.path.join(d, ".env")
        with open(env, "w", encoding="utf-8") as f:
            f.write("NAVER_AD_API_KEY=a\nSUPABASE_URL=https://x.supabase.co\nSUPABASE_KEY=k\n")
        config.save_env({"NAVER_AD_API_KEY": "b"}, env)
        v = config.load_env(env)
        assert v["NAVER_AD_API_KEY"] == "b" and v["SUPABASE_URL"] == "https://x.supabase.co" and v["SUPABASE_KEY"] == "k"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ❌ {t.__name__}: {e!r}")
    print("✅ 전부 통과" if not failed else f"❌ {failed}개 실패")
    sys.exit(1 if failed else 0)
