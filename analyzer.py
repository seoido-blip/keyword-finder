"""
분석 로직 (화면과 분리 — app.py / cli.py 가 함께 쓴다)

이 파일의 구성
  1) enrich_with_documents  키워드마다 '한 달 기준' 발행량·포화지수를 붙인다
  2) keyword_detail         키워드 하나의 상세(기본 정보 탭) — 검색량, 월 발행량, 이번 달 예상 검색량
  3) discover               🏆 황금 키워드 추천 — 연관 키워드 + 2단계 확장 + 비슷한 표현(근처·밥집…)
  4) discover_region        📍 지역 키워드 — 동네·명소 찾기(블로그 함께 언급으로 검증) + 다른 구·군 비교
  5) run / expand_keywords  예전 방식(여러 시드 → 연관 키워드 표). cli.py 의 --legacy 에서 사용

핵심 지표 (블랙키위 방식, 모두 '한 달' 기준)
  월간 검색량  = PC + 모바일 (검색광고 API, 최근 30일)
  월 블로그 발행 = 최근 30일 새 블로그 글 수 (1,000건 넘으면 발행 속도로 추정 → '추정' 표시)
  월 카페 발행  = 카페 누적 글 × (블로그 최근 30일 ÷ 블로그 누적)  ※ 카페 검색엔 작성일이 없어 추정
  포화지수(%)  = 월 발행량 ÷ 월간 검색량 × 100   → 낮을수록 '찾는 사람은 많은데 글은 적은' 좋은 키워드
  추천점수     = 검색량 점수(50) + 경쟁 점수(50)
"""

from __future__ import annotations

import calendar
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from naver_api import OpenApiClient, SearchAdClient
from region import extract_neighborhoods, keyword_forms, parse_region, region_label, sibling_keywords


def grade(saturation: float, recent_mode: bool) -> str:
    """포화지수 → 등급. 기준값은 config 성격이라 여기서 조정하면 된다."""
    # 최근 30일 기준: 검색량 대비 월 발행량 비율(%)
    # 누적 기준: 누적 문서가 검색량의 몇 배인지(%)라 기준을 크게 잡는다
    cuts = [10, 30, 70, 150] if recent_mode else [50, 200, 600, 2000]
    labels = ["🟢 매우좋음", "🟢 좋음", "🟡 보통", "🟠 나쁨", "🔴 매우나쁨"]
    for c, label in zip(cuts, labels):
        if saturation < c:
            return label
    return labels[-1]


def expand_keywords(ad: SearchAdClient, seeds: list[str]) -> pd.DataFrame:
    """시드 키워드 → 연관 키워드 + 검색량. 5개씩 나눠 호출."""
    rows: list[dict] = []
    for i in range(0, len(seeds), 5):
        rows.extend(ad.keyword_tool(seeds[i : i + 5]))
        time.sleep(0.2)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    seed_set = {s.replace(" ", "") for s in seeds}
    df["시드"] = df["키워드"].isin(seed_set)
    return df.drop_duplicates("키워드").reset_index(drop=True)


SAT_EMOJI = {"매우 낮음": "🟢", "낮음": "🟢", "보통": "🟡", "높음": "🟠", "매우 높음": "🔴"}


def enrich_with_documents(
    api: OpenApiClient,
    df: pd.DataFrame,
    count_recent: bool = True,
    include_cafe: bool = True,
    workers: int = 5,
    progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """
    각 키워드에 '한 달 기준' 발행량과 포화지수를 붙인다 (블랙키위 방식).
    - 월 블로그 발행 : 최근 30일 동안 새로 올라온 블로그 글 수
    - 월 카페 발행   : 카페 누적 글 × (블로그 최근 30일 ÷ 블로그 누적) 으로 추정 (카페 검색엔 작성일이 없음)
    - 포화지수       : 월 발행량 ÷ 월간 검색량 × 100  (낮을수록 좋음)
    count_recent=False 면 예전 방식(누적 문서 수 기준)으로 빠르게 계산한다.
    """
    keywords = df["키워드"].tolist()
    results: dict[str, dict] = {}

    def work(kw: str) -> tuple[str, dict]:
        out = {"블로그 누적 발행량": None, "카페 누적 발행량": None, "월 블로그 발행": None, "추정": False}
        try:
            out["블로그 누적 발행량"] = api.blog_total(kw)
            if include_cafe:
                out["카페 누적 발행량"] = api.cafe_total(kw)
            if count_recent:
                n, est = api.blog_recent_count(kw)
                out["월 블로그 발행"], out["추정"] = n, est
        except Exception as e:  # 한 키워드 실패해도 계속
            out["오류"] = str(e)[:120]
        return kw, out

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (kw, out) in enumerate(ex.map(work, keywords), 1):
            results[kw] = out
            if progress:
                progress(i, len(keywords))

    extra = pd.DataFrame.from_dict(results, orient="index")
    if "오류" not in extra.columns:
        extra["오류"] = None
    df = df.join(extra, on="키워드")
    vol = df["월간 검색량"].clip(lower=1)
    btot = df["블로그 누적 발행량"].fillna(0)
    ctot = df["카페 누적 발행량"].fillna(0)

    if count_recent:
        # 날짜순 검색이 누적 문서 수보다 많게 나오는 경우가 있어 누적 수를 넘지 않게 자른다
        blog = df["월 블로그 발행"].fillna(0).clip(upper=btot)
        df["월 블로그 발행"] = blog.astype(int)
        # 카페 추정에 쓰는 '한 달 비율'은 최대 20%로 제한 (추정치가 터무니없이 커지는 것 방지)
        ratio = (blog / btot.where(btot > 0)).fillna(0).clip(upper=0.2)
        cafe = (ctot * ratio).round().astype(int)
        df["월 카페 발행"] = cafe
        df["월 전체 발행"] = (blog + cafe).astype(int)
        df["블로그 포화(%)"] = (blog / vol * 100).round(2)
        df["카페 포화(%)"] = (cafe / vol * 100).round(2)
        df["전체 포화(%)"] = (df["월 전체 발행"] / vol * 100).round(2)
        df["포화지수(%)"] = df["전체 포화(%)"]
        df["경쟁도"] = df["전체 포화(%)"].apply(lambda p: f"{SAT_EMOJI[sat_level(p)[0]]} {sat_level(p)[0]}")
        df["등급"] = df["경쟁도"]
    else:
        df["포화지수(%)"] = (btot / vol * 100).round(1)
        df["등급"] = df["포화지수(%)"].apply(lambda s: grade(s, False))
    df["총 클릭수"] = (df["PC 클릭수"] + df["모바일 클릭수"]).round(1)
    df["모바일 비중(%)"] = (df["모바일 검색량"] / vol * 100).round(0)
    return df


COLUMN_ORDER = [
    "등급", "키워드", "월간 검색량", "PC 검색량", "모바일 검색량", "모바일 비중(%)",
    "월 블로그 발행", "월 카페 발행", "월 전체 발행", "블로그 포화(%)", "카페 포화(%)", "전체 포화(%)",
    "블로그 누적 발행량", "카페 누적 발행량", "포화지수(%)",
    "총 클릭수", "PC 클릭률(%)", "모바일 클릭률(%)", "광고 경쟁", "광고 노출수", "시드", "오류",
]


def tidy(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in COLUMN_ORDER if c in df.columns]
    return df[cols]


def run(
    ad: SearchAdClient,
    api: OpenApiClient,
    seeds: list[str],
    min_volume: int = 100,
    max_keywords: int = 100,
    count_recent: bool = False,
    include_cafe: bool = True,
    progress=None,
) -> pd.DataFrame:
    df = expand_keywords(ad, seeds)
    if df.empty:
        return df
    # 문서 수 조회는 API 호출이 많으므로 검색량 상위 N개만
    df = df[(df["월간 검색량"] >= min_volume) | df["시드"]]
    df = df.sort_values(["시드", "월간 검색량"], ascending=[False, False]).head(max_keywords)
    df = enrich_with_documents(api, df, count_recent, include_cafe, progress=progress)
    return tidy(df.sort_values("포화지수(%)").reset_index(drop=True))


# ---------------------------------------------------------------------------
# 단일 키워드 상세 분석 (블랙키위 '기본 정보' 화면)
# ---------------------------------------------------------------------------

# 월간 발행량 ÷ 월간 검색량 × 100 기준 포화도 구간
SAT_LEVELS = [(10, "매우 낮음", "#12b886"), (30, "낮음", "#40c057"), (50, "보통", "#fab005"),
              (70, "높음", "#fd7e14"), (float("inf"), "매우 높음", "#fa5252")]
GRADE_BY_SAT = [(10, "A"), (30, "B"), (70, "C"), (150, "D"), (float("inf"), "E")]


def sat_level(p: float) -> tuple[str, str]:
    for cut, label, color in SAT_LEVELS:
        if p < cut:
            return label, color
    return SAT_LEVELS[-1][1:]


def keyword_grade(p: float) -> str:
    for cut, g in GRADE_BY_SAT:
        if p < cut:
            return g
    return "E"


def month_search_estimate(api: OpenApiClient, keyword: str, monthly_volume: int, today: date | None = None) -> dict:
    """
    데이터랩 일별 상대값(최근 60일)을 검색광고 API의 최근 30일 검색량에 맞춰 환산해
    '이번 달 어제까지 검색량'과 '이번 달 말 예상 검색량'을 구한다.
    """
    today = today or date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=59)
    rows = api.datalab_trend(keyword, start=start, end=end, unit="date")
    ratio = {r["period"]: float(r["ratio"]) for r in rows}
    days = [end - timedelta(days=i) for i in range(60)]
    val = lambda d: ratio.get(d.strftime("%Y-%m-%d"), 0.0)
    last30 = sum(val(d) for d in days[:30])
    if last30 <= 0:
        return {"ok": False}
    scale = monthly_volume / last30
    month_days = [d for d in days if d.year == today.year and d.month == today.month]
    mtd = sum(val(d) for d in month_days) * scale
    avg7 = sum(val(d) for d in days[:7]) / 7 * scale
    dim = calendar.monthrange(today.year, today.month)[1]
    remaining = dim - len(month_days)
    projected = mtd + avg7 * remaining
    # 지난달 같은 기간 대비 증감
    prev_end = today.replace(day=1) - timedelta(days=1)
    prev_month_total = sum(val(d) for d in days if d.year == prev_end.year and d.month == prev_end.month) * scale
    prev_same = sum(val(d) for d in days if d.year == prev_end.year and d.month == prev_end.month
                    and d.day <= len(month_days)) * scale
    pct = lambda a, b: (a - b) / b * 100 if b else None
    return {
        "ok": True,
        "month": today.month,
        "upto_day": len(month_days),
        "days_in_month": dim,
        "mtd": int(mtd),
        "projected": int(projected),
        "mtd_change": pct(mtd, prev_same),
        "projected_change": pct(projected, prev_month_total),
        "daily": [{"날짜": d.strftime("%Y-%m-%d"), "검색량": round(val(d) * scale)} for d in reversed(days)],
    }


def keyword_detail(ad: SearchAdClient, api: OpenApiClient, keyword: str) -> dict:
    kw = keyword.replace(" ", "")
    related = ad.keyword_tool([kw])
    row = next((r for r in related if r["키워드"].replace(" ", "").lower() == kw.lower()), None)
    if row is None:
        row = {"키워드": keyword, "PC 검색량": 0, "모바일 검색량": 0, "월간 검색량": 0,
               "PC 클릭수": 0, "모바일 클릭수": 0, "PC 클릭률(%)": 0, "모바일 클릭률(%)": 0,
               "광고 노출수": 0, "광고 경쟁": "-"}
    vol = row["월간 검색량"]

    blog_total = api.blog_total(keyword)
    cafe_total = api.cafe_total(keyword)
    blog_30, blog_est = api.blog_recent_count(keyword)
    # 카페 검색 결과에는 작성일이 없어 → 블로그의 '최근 30일 비율'을 카페 누적량에 적용해 추정
    cafe_30 = int(cafe_total * blog_30 / blog_total) if blog_total else 0
    total_30 = blog_30 + cafe_30

    base = max(vol, 1)
    sat = {"블로그": blog_30 / base * 100, "카페": cafe_30 / base * 100, "전체": total_30 / base * 100}

    d = {
        "keyword": keyword, "row": row, "related": related,
        "blog_total": blog_total, "cafe_total": cafe_total,
        "blog_30": blog_30, "blog_est": blog_est, "cafe_30": cafe_30, "total_30": total_30,
        "sat": sat, "grade": keyword_grade(sat["전체"]),
        "mobile_share": row["모바일 검색량"] / base * 100,
        "clicks": row["PC 클릭수"] + row["모바일 클릭수"],
        "month": {"ok": False}, "trend": [], "trend_error": None,
    }
    try:
        d["month"] = month_search_estimate(api, keyword, vol)
        d["trend"] = api.datalab_trend(keyword, months=12, unit="month")
    except Exception as e:  # 검색어 트렌드 API를 추가하지 않은 경우 등
        d["trend_error"] = str(e)[:200]
    return d


# ---------------------------------------------------------------------------
# 황금 키워드 자동 추천
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    return s.replace(" ", "").lower()


def is_relevant(keyword: str, tokens: list[str], mode: str) -> bool:
    """mode: first(첫 단어=주제 포함) | all(모두 포함) | any(하나라도 포함) | none(거르지 않음)"""
    if mode == "none" or not tokens:
        return True
    k = _norm(keyword)
    if mode == "first":
        return _norm(tokens[0]) in k
    hits = [_norm(t) in k for t in tokens]
    return all(hits) if mode == "all" else any(hits)


RELAX_ORDER = ["all", "first", "any", "none"]


def split_tokens(query: str, related: list[str]) -> list[str]:
    """
    띄어쓰기가 없으면('팔공산맛집') 연관 키워드에 가장 많이 등장하는 앞/뒤 조각으로 나눈다 → ['팔공산', '맛집']
    """
    tokens = [t for t in query.split() if t]
    if len(tokens) > 1 or len(query.strip()) < 4:
        return tokens
    q = _norm(query)
    kws = [_norm(k) for k in related if _norm(k) != q]
    best, best_score = tokens, 0
    for i in range(2, len(q) - 1):
        a, b = q[:i], q[i:]
        ca, cb = sum(a in k for k in kws), sum(b in k for k in kws)
        if ca >= 2 and cb >= 2 and ca + cb > best_score:
            best, best_score = [a, b], ca + cb
    return best


def recommend_score(volume: float, saturation: float, recent_mode: bool) -> int:
    """
    추천점수(0~100) = 검색량 점수(최대 50) + 경쟁 점수(최대 50)
    - 검색량 점수: 1천=30, 1만=40, 10만 이상=50 (로그 비례)
    - 경쟁 점수 : 포화지수 0이면 50, 기준값(누적 200% / 30일 30%)이면 25, 높을수록 0에 가까움
    """
    vol_score = 50 * min(1.0, math.log10(max(volume, 1)) / 5)
    ref = 30 if recent_mode else 200
    comp_score = 50 / (1 + max(saturation, 0) / ref)
    return int(round(vol_score + comp_score))


# 업종별로 사람들이 바꿔 쓰는 표현
CATEGORY_SYNONYMS = {
    "맛집": ["밥집", "식당", "음식점", "맛집추천", "맛집베스트", "현지인맛집", "점심", "저녁", "데이트", "가족외식",
           "한식", "고기집", "한정식", "백숙", "오리고기", "브런치"],
    "카페": ["커피", "대형카페", "뷰카페", "신상카페", "카페추천", "디저트", "베이커리", "빵집", "브런치카페", "애견카페"],
    "숙소": ["펜션", "호텔", "모텔", "숙박", "글램핑", "캠핑장", "독채펜션", "풀빌라"],
    "펜션": ["숙소", "독채펜션", "풀빌라", "글램핑", "캠핑장", "숙박", "펜션추천"],
    "술집": ["이자카야", "포차", "호프", "와인바", "룸술집", "분위기좋은술집", "술집추천"],
    "횟집": ["회", "물회", "해산물", "조개구이", "횟집추천", "대게"],
    "가볼만한곳": ["관광지", "볼거리", "놀거리", "데이트코스", "드라이브", "산책", "명소", "여행", "아이와가볼만한곳"],
    "미용실": ["헤어샵", "펌", "염색", "미용실추천", "남자미용실"],
    "병원": ["의원", "병원추천", "피부과", "치과", "정형외과", "한의원"],
}
LOCATION_MODIFIERS = ["근처", "주변", "인근", "앞"]
SUFFIX_MODIFIERS = ["추천", "베스트", "best", "순위", "가성비"]


def variant_keywords(place: str, category: str, limit: int = 40) -> list[str]:
    """
    '팔공산 맛집' → 팔공산근처맛집, 팔공산주변맛집, 팔공산밥집, 팔공산식당, 팔공산맛집추천 …
    사람들이 같은 뜻으로 바꿔서 검색할 만한 표현을 만든다 (검색량은 나중에 조회해서 있는 것만 쓴다).
    """
    p, c = _norm(place), _norm(category)
    out = []
    if c:
        out += [f"{p}{m}{c}" for m in LOCATION_MODIFIERS]
        out += [f"{p}{c}{m}" for m in SUFFIX_MODIFIERS]
        out += [f"{p}{syn}" for syn in CATEGORY_SYNONYMS.get(c, [])]
        out += [f"{p}{m}{syn}" for syn in CATEGORY_SYNONYMS.get(c, [])[:3] for m in LOCATION_MODIFIERS[:2]]
    else:
        out += [f"{p}{x}" for x in ["맛집", "카페", "가볼만한곳", "근처맛집", "주변맛집", "데이트", "드라이브",
                                    "숙소", "펜션", "주차", "날씨", "코스"]]
    seen, res = {_norm(f"{p}{c}")}, []
    for k in out:
        if k not in seen:
            seen.add(k)
            res.append(k)
    return res[:limit]


def discover(
    ad: SearchAdClient,
    api: OpenApiClient,
    query: str,
    deep: bool = True,
    match: str = "any",
    min_volume: int = 100,
    max_check: int = 60,
    count_recent: bool = True,
    progress=None,
) -> tuple[pd.DataFrame, dict]:
    q = _norm(query)
    rows: dict[str, dict] = {r["키워드"]: r for r in ad.keyword_tool([query])}
    first_round = len(rows)
    tokens = split_tokens(query, list(rows))

    # 2단계 확장: 관련성 있는 상위 연관 키워드 5개를 다시 힌트로 넣어 더 넓게 수집
    if deep:
        seeds = sorted(
            (r for r in rows.values() if _norm(r["키워드"]) != q and is_relevant(r["키워드"], tokens, match)),
            key=lambda r: r["월간 검색량"], reverse=True,
        )[:5]
        if seeds:
            for r in ad.keyword_tool([s["키워드"] for s in seeds]):
                rows.setdefault(r["키워드"], r)

    # 3) 비슷한 표현(근처·주변·밥집·식당 …)을 만들어 검색량 조회
    variants_found: list[dict] = []
    if tokens:
        place = tokens[0]
        cat = "".join(tokens[1:])
        vrows: dict[str, dict] = {}
        _lookup(ad, variant_keywords(place, cat), vrows)
        vset = {_norm(v) for v in variant_keywords(place, cat)}
        for k, r in vrows.items():
            if k in vset:
                variants_found.append(r)
            rows.setdefault(r["키워드"], r)
    source = {}
    for r in variants_found:
        source[r["키워드"]] = "비슷한 표현"

    df = pd.DataFrame(list(rows.values()))
    info = {"tokens": tokens, "collected": len(df), "first_round": first_round, "relaxed": None,
            "variants": sorted(((r["키워드"], r["월간 검색량"]) for r in variants_found),
                               key=lambda x: x[1], reverse=True)}
    if df.empty:
        return df, info

    # 관련 키워드가 너무 적으면(5개 미만) 필터를 한 단계씩 풀어 준다
    used = match
    for mode in RELAX_ORDER[RELAX_ORDER.index(match):]:
        used = mode
        rel = df[df["키워드"].apply(lambda k: is_relevant(k, tokens, mode))]
        if len(rel) >= 5:
            break
    if used != match:
        info["relaxed"] = used
    info["relevant"] = len(rel)

    cand = rel[(rel["월간 검색량"] >= min_volume) | (rel["키워드"].map(_norm) == q)]
    top = cand.sort_values("월간 검색량", ascending=False).head(max_check)
    # 비슷한 표현은 검색량 순위에 밀려 빠지지 않도록 따로 챙긴다 (최소 검색량의 절반 이상, 최대 20개)
    vk = {k for k, v in info["variants"] if v >= max(min_volume // 2, 10)}
    extra = rel[rel["키워드"].isin(vk) & ~rel["키워드"].isin(top["키워드"])].sort_values(
        "월간 검색량", ascending=False).head(20)
    cand = pd.concat([top, extra]).copy()
    info["checked"] = len(cand)
    if cand.empty:
        return cand, info
    cand["시드"] = cand["키워드"].map(_norm) == q
    cand["출처"] = cand["키워드"].map(lambda k: source.get(k, "연관 키워드"))

    out = enrich_with_documents(api, cand, count_recent, True, progress=progress)
    info["failed"] = out.loc[out["오류"].notna(), "키워드"].tolist()
    out = out[out["오류"].isna()].copy()  # 조회 실패한 키워드는 0으로 잘못 추천되지 않게 뺀다
    out["추천점수"] = [
        recommend_score(v, s, count_recent) for v, s in zip(out["월간 검색량"], out["포화지수(%)"])
    ]
    out = out.sort_values("추천점수", ascending=False).reset_index(drop=True)
    return out, info


# ---------------------------------------------------------------------------
# 지역 키워드: 같은 지역 동네·명소 + 같은 시·도 다른 구·군 비교
# ---------------------------------------------------------------------------


def _lookup(ad: SearchAdClient, hints: list[str], rows: dict[str, dict]) -> list[dict]:
    """힌트를 5개씩 조회해 rows(정규화 키워드 → 행)에 모으고, 이번에 받은 행을 돌려준다."""
    got = []
    for i in range(0, len(hints), 5):
        try:
            batch = ad.keyword_tool(hints[i:i + 5])
        except RuntimeError:
            # 묶음 중 하나가 문제면 하나씩 다시 (검색 이력이 없는 형태 등은 건너뛴다)
            batch = []
            for h in hints[i:i + 5]:
                try:
                    batch += ad.keyword_tool([h])
                except RuntimeError:
                    pass
                time.sleep(0.15)
        for r in batch:
            rows.setdefault(_norm(r["키워드"]), r)
        got.extend(batch)
        time.sleep(0.2)
    return got


def verify_neighborhoods(api: OpenApiClient, r: dict, cands: list[tuple[str, str]], progress=None,
                         workers: int = 6) -> tuple[list[tuple[str, str]], list[str]]:
    """
    블로그 검색 결과 수로 동네·명소가 내 지역 것인지 확인한다. (실데이터로 맞춘 기준)
    ① '대구 X' 글이 'X' 글의 20% 이상 (키워드에 '대구'가 붙어 있으면 8%, 시·도만 입력했으면 30%)
       → 다른 도시(해운대·탕정·조치원 …) 제외
    ② 구까지 입력했다면
       - '대구 동구 X' 글이 다른 구('대구 수성구 X' …)보다 가장 많거나 90% 이상이고
       - 'X' 전체 글 중 '대구 동구 X'가 5% 이상 → 마산·진해·왜관·언양 같은 인근 도시 제외
    """
    from region import REGIONS

    cache: dict[str, int] = {}

    def total(q: str) -> int:
        if q not in cache:
            try:
                cache[q] = api.blog_total(q)
            except Exception:
                cache[q] = 0
        return cache[q]

    sido, gu = r["sido"], r["gu"]
    gus = [g for g in REGIONS.get(sido, []) if not (sido == "인천" and g in ("중구", "동구"))]
    n = max(len(cands), 1)

    def check(h):
        name, kw = h
        alone, with_sido = total(name), total(f"{sido} {name}")
        sido_ratio = with_sido / alone * 100 if alone else 0
        m = {"동네": name, "단독 글수": f"{alone:,}", "시도 비율": f"{sido_ratio:.1f}%"}
        # 키워드 자체에 시·도 이름이 붙어 있으면(대구혁신도시맛집) 흔한 이름이라도 8%, 아니면 20%(시·도만 입력 시 30%)
        need = 8 if _norm(kw).startswith(sido) else (20 if gu else 30)
        ok = alone > 0 and sido_ratio >= need
        if ok and gu and gus:
            counts = {g: total(f"{sido} {g} {name}") for g in gus}
            mine = counts.get(gu, 0)
            top_g = max(counts, key=counts.get)
            gu_ratio = mine / alone * 100
            share = mine / counts[top_g] * 100 if counts[top_g] else 0
            m.update({"구 비율": f"{gu_ratio:.1f}%", "가장 많이 언급된 구": top_g, "최다 대비": f"{share:.0f}%"})
            ok = share >= 90 and gu_ratio >= 5
        m["판정"] = "✅ 포함" if ok else "🚫 제외"
        return h, ok, m

    keep, rejected, metrics = [], [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (h, ok, m) in enumerate(ex.map(check, cands), 1):
            (keep if ok else rejected).append(h if ok else h[0])
            metrics.append(m)
            if progress:  # 화면 갱신은 메인 스레드에서만
                progress(i, n)
    verify_neighborhoods.last_metrics = metrics
    return keep, rejected


def infer_region(api: OpenApiClient, place: str, category: str) -> dict | None:
    """
    행정구역 이름이 없는 명소·동네(팔공산, 성수동 …)가 어느 시·도/구·군인지
    블로그에 함께 언급되는 횟수로 알아낸다.
    """
    from region import REGIONS

    def total(q: str) -> int:
        try:
            return api.blog_total(q)
        except Exception:
            return 0

    alone = total(place)
    if alone <= 0:
        return None
    sidos = list(REGIONS)
    with ThreadPoolExecutor(max_workers=5) as ex:
        counts = dict(zip(sidos, ex.map(lambda sd: total(f"{sd} {place}"), sidos)))
    ranked = sorted(counts, key=counts.get, reverse=True)
    best, second = ranked[0], ranked[1]
    if counts[best] / alone < 0.15 or counts[best] < 1.3 * counts[second]:
        return None  # 여러 지역에 흔한 이름이면 판단하지 않는다
    gus = [g for g in REGIONS[best] if not (best == "인천" and g in ("중구", "동구"))]
    gu = None
    if gus:
        with ThreadPoolExecutor(max_workers=5) as ex:
            gc = dict(zip(gus, ex.map(lambda g: total(f"{best} {g} {place}"), gus)))
        gr = sorted(gc, key=gc.get, reverse=True)
        if gc[gr[0]] > 0 and (len(gr) == 1 or gc[gr[0]] >= 1.3 * gc[gr[1]]):
            gu = gr[0]
    return {"sido": best, "gu": gu, "category": category, "anchor": place}


def discover_region(
    ad: SearchAdClient,
    api: OpenApiClient,
    query: str,
    min_volume: int = 50,
    max_neighborhoods: int = 30,
    count_recent: bool = True,
    progress=None,
) -> dict | None:
    rows: dict[str, dict] = {}
    r = parse_region(query)
    related: list[dict] = []
    if r is None:
        # 행정구역 이름이 없으면(팔공산 맛집) 명소 이름으로 지역을 추정
        related = _lookup(ad, [query], rows)
        toks = split_tokens(query, [x["키워드"] for x in related])
        if len(toks) < 2:
            return None
        r = infer_region(api, toks[0], "".join(toks[1:]))
        if r is None:
            return {"region": None, "anchor": toks[0]}
    if not r["category"]:
        return None

    # 1) 내 지역 키워드의 연관 키워드 → 동네·명소 후보
    own_forms = keyword_forms(r["sido"], r["gu"], r["category"])
    related += _lookup(ad, own_forms, rows)
    hoods = extract_neighborhoods(r, [x["키워드"] for x in related])
    # 2단계: 검색량 많은 동네 키워드 5개로 한 번 더 확장
    top = sorted(hoods, key=lambda h: rows.get(_norm(h[1]), {}).get("월간 검색량", 0), reverse=True)[:5]
    if top:
        more = _lookup(ad, [h[1] for h in top], rows)
        known = {h[0] for h in hoods}
        hoods += [h for h in extract_neighborhoods(r, [x["키워드"] for x in more]) if h[0] not in known]

    if r.get("anchor"):  # 검색한 명소 자체는 동네 목록에서 뺀다
        hoods = [h for h in hoods if _norm(h[0]) != _norm(r["anchor"])]

    # 1-2) 동네가 정말 내 지역 것인지 블로그 '함께 언급' 횟수로 확인
    cand = sorted({h[0]: h for h in hoods}.values(),
                  key=lambda h: rows.get(_norm(h[1]), {}).get("월간 검색량", 0), reverse=True)
    cand = [h for h in cand if rows.get(_norm(h[1]), {}).get("월간 검색량", 0) >= min_volume][:max_neighborhoods + 10]
    hoods, rejected = verify_neighborhoods(api, r, cand, progress)

    # 2) 같은 시·도의 다른 구·군 (형태별 검색량 중 가장 큰 것을 대표로)
    sibs = sibling_keywords(r)
    _lookup(ad, [f for _, forms in sibs for f in forms if _norm(f) not in rows], rows)

    def best(forms):
        cands = [rows[_norm(f)] for f in forms if _norm(f) in rows]
        return max(cands, key=lambda x: x["월간 검색량"]) if cands else None

    items = []
    own = best(own_forms)
    if own:
        items.append({**own, "구분": "내 지역", "지역": region_label(r)})
    for label, forms in sibs:
        b = best(forms)
        if b:
            items.append({**b, "구분": "다른 구·군", "지역": label})
    hood_items = []
    for name, kw in hoods:
        row = rows.get(_norm(kw))
        if row and row["월간 검색량"] >= min_volume:
            hood_items.append({**row, "구분": "동네·명소", "지역": name})
    hood_items = sorted(hood_items, key=lambda x: x["월간 검색량"], reverse=True)[:max_neighborhoods]

    df = pd.DataFrame(items + hood_items)
    if df.empty:
        return {"region": r, "df": df, "rejected": rejected}
    df = df.drop_duplicates("키워드").reset_index(drop=True)
    df = enrich_with_documents(api, df, count_recent, True, progress=progress)
    df = df[df["오류"].isna()].copy()
    df["추천점수"] = [recommend_score(v, s, count_recent) for v, s in zip(df["월간 검색량"], df["포화지수(%)"])]
    return {"region": r, "df": df.sort_values("추천점수", ascending=False).reset_index(drop=True),
            "rejected": rejected, "metrics": getattr(verify_neighborhoods, "last_metrics", [])}
