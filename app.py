"""
네이버 키워드 파인더 (블랙키위 스타일 대시보드)
실행:  streamlit run app.py   (또는 실행.bat)
"""

import importlib
import io
from html import escape

import pandas as pd
import streamlit as st

import analyzer as _an
import config as _cf
import naver_api as _na
import region as _rg

# 프로그램 파일이 업데이트되면 새로고침(F5)만으로 반영되도록 매번 다시 읽는다
for _m in (_na, _cf, _rg, _an):
    importlib.reload(_m)

from analyzer import discover, discover_region, keyword_detail, sat_level
from region import parse_region, region_label
from config import load_env, save_env
from naver_api import OpenApiClient, SearchAdClient

st.set_page_config(page_title="네이버 키워드 파인더", page_icon="🔑", layout="wide")

# ---------------------------------------------------------------- 스타일
st.markdown(
    """
<style>
.block-container {padding-top: 1.6rem; max-width: 1400px;}
.kf-head {background:#111; color:#fff; padding:18px 26px; border-radius:14px; margin-bottom:18px;
          display:flex; align-items:center; gap:14px;}
.kf-head b {font-size:22px; letter-spacing:.5px;}
.kf-head span {color:#aaa; font-size:14px;}
.kf-mini {background:#fff; border-radius:12px; box-shadow:0 1px 4px rgba(0,0,0,.08);
          padding:16px 22px; min-height:112px;}
.kf-mini .t {color:#666; font-size:14px;}
.kf-mini .v {font-size:clamp(20px,2vw,26px); margin-top:6px; font-weight:500;}
.kf-card {background:#fff; border-radius:12px; box-shadow:0 1px 4px rgba(0,0,0,.08);
          margin-bottom:18px; overflow:hidden;}
.kf-card .h {padding:16px 24px; border-bottom:1px solid #eee; font-size:17px; font-weight:600;}
.kf-card .h small {color:#999; font-weight:400; font-size:12px; margin-left:6px;}
.kf-card .b {display:flex; flex-wrap:wrap; justify-content:space-around; gap:18px 6px; padding:30px 10px 26px;}
.kf-item {text-align:center; flex:1 1 100px; min-width:0;}
.kf-ic {width:62px; height:62px; border-radius:50%; background:#f1f3f5; margin:0 auto 14px;
        display:flex; align-items:center; justify-content:center; font-size:26px;}
.kf-num {font-size:clamp(22px,2.2vw,32px); font-weight:400; color:#222; white-space:nowrap;}
.kf-sub {font-size:13px; margin-top:2px;}
.kf-lab {color:#888; font-size:14px; margin-top:4px;}
.kf-note {color:#999; font-size:12px; padding:0 24px 14px;}
.kf-grid {display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr)); gap:14px; margin:8px 0 18px;}
.kf-rec {background:#fff; border-radius:12px; box-shadow:0 1px 4px rgba(0,0,0,.08); padding:16px 18px;
         border-top:4px solid #12b886;}
.kf-rec .rk {color:#999; font-size:12px;}
.kf-rec .kw {font-size:18px; font-weight:600; margin:2px 0 10px; word-break:keep-all;}
.kf-rec .sc {float:right; background:#e6fcf5; color:#0ca678; border-radius:20px; padding:2px 10px;
             font-size:13px; font-weight:600;}
.kf-rec .tg {background:#e7f5ff; color:#1971c2; border-radius:10px; padding:1px 7px; font-size:11px; margin-left:4px;}
.kf-chips {display:flex; flex-wrap:wrap; gap:6px; margin:4px 0 14px;}
.kf-chip {background:#fff; border:1px solid #dee2e6; border-radius:16px; padding:4px 11px; font-size:13px;}
.kf-chip b {color:#1971c2; margin-left:4px;}
.kf-rec .sec {font-size:12px; color:#888; margin:10px 0 4px; border-top:1px solid #f1f3f5; padding-top:8px;}
.kf-rec .sec span {color:#bbb;}
.kf-rec .row3 {display:grid; grid-template-columns:repeat(3,1fr); text-align:center;}
.kf-rec .row3 .v {font-size:16px; color:#222;}
.kf-rec .row3 .v.b {font-weight:700;}
.kf-rec .row3 .l {font-size:11px; color:#999;}
.kf-rec .row3 .lv {font-size:11px; font-weight:600;}
</style>
""",
    unsafe_allow_html=True,
)


def fmt(n) -> str:
    try:
        return f"{int(round(n)):,}"
    except (TypeError, ValueError):
        return "-"


def card(title: str, items: list[dict], help_text: str = "", note: str = "") -> str:
    """items: [{icon, value, label, sub, sub_color}]"""
    body = ""
    for it in items:
        sub = ""
        if it.get("sub"):
            sub = f'<div class="kf-sub" style="color:{it.get("sub_color", "#888")}">{escape(it["sub"])}</div>'
        body += (
            f'<div class="kf-item"><div class="kf-ic">{it["icon"]}</div>'
            f'<div class="kf-num">{escape(str(it["value"]))}</div>{sub}'
            f'<div class="kf-lab">{escape(it["label"])}</div></div>'
        )
    small = f"<small>{escape(help_text)}</small>" if help_text else ""
    nt = f'<div class="kf-note">{escape(note)}</div>' if note else ""
    return f'<div class="kf-card"><div class="h">{escape(title)}{small}</div><div class="b">{body}</div>{nt}</div>'


def mini(title: str, value: str, color: str = "#222") -> str:
    return (f'<div class="kf-mini"><div class="t">{escape(title)}</div>'
            f'<div class="v" style="color:{color}">{escape(value)}</div></div>')


def change_text(p):
    if p is None:
        return "", "#888"
    arrow = "▲" if p >= 0 else "▼"
    return f"{abs(p):.1f}% {arrow} 지난달 대비", ("#2f9e44" if p >= 0 else "#fa5252")


def _sat_html(p: float) -> str:
    lv, color = sat_level(p)
    return (f'<div class="v">{p:.2f}%</div><div class="lv" style="color:{color}">{lv}</div>')


def rec_cards(records: list[dict], name_col: str = "키워드", rank_label: str = "추천") -> str:
    """블랙키위처럼: 월간 검색량 / 월간 발행량 / 포화지수 를 PC·모바일·합계, 블로그·카페·전체로 한눈에."""
    html = '<div class="kf-grid">'
    for i, rd in enumerate(records, 1):
        lv, color = sat_level(rd.get("전체 포화(%)", rd.get("포화지수(%)", 0)))
        title = rd[name_col]
        sub = (f'<div class="rk" style="margin:-6px 0 8px">{escape(rd["키워드"])}</div>'
               if name_col != "키워드" else "")
        est = "*" if rd.get("추정") else ""
        tag = ('<span class="tg">🔁 비슷한 표현</span>' if rd.get("출처") == "비슷한 표현" else "")
        html += (
            f'<div class="kf-rec" style="border-top-color:{color}">'
            f'<span class="sc">{rd["추천점수"]}점</span><div class="rk">{rank_label} {i}위 {tag}</div>'
            f'<div class="kw">{escape(str(title))}</div>{sub}'
            f'<div class="sec">월간 검색량</div><div class="row3">'
            f'<div><div class="v">{fmt(rd["PC 검색량"])}</div><div class="l">PC</div></div>'
            f'<div><div class="v">{fmt(rd["모바일 검색량"])}</div><div class="l">모바일</div></div>'
            f'<div><div class="v b">{fmt(rd["월간 검색량"])}</div><div class="l">합계</div></div></div>'
            f'<div class="sec">월간 발행량 <span>(최근 30일)</span></div><div class="row3">'
            f'<div><div class="v">{fmt(rd["월 블로그 발행"])}{est}</div><div class="l">블로그</div></div>'
            f'<div><div class="v">{fmt(rd["월 카페 발행"])}</div><div class="l">카페</div></div>'
            f'<div><div class="v b">{fmt(rd["월 전체 발행"])}</div><div class="l">전체</div></div></div>'
            f'<div class="sec">포화지수</div><div class="row3">'
            f'<div>{_sat_html(rd["블로그 포화(%)"])}<div class="l">블로그</div></div>'
            f'<div>{_sat_html(rd["카페 포화(%)"])}<div class="l">카페</div></div>'
            f'<div>{_sat_html(rd["전체 포화(%)"])}<div class="l">전체</div></div></div>'
            f'</div>'
        )
    return html + "</div>"


MONTH_COLS = ["월간 검색량", "PC 검색량", "모바일 검색량", "월 블로그 발행", "월 카페 발행", "월 전체 발행",
              "블로그 포화(%)", "카페 포화(%)", "전체 포화(%)"]
MONTH_CFG = {
    "추천점수": st.column_config.ProgressColumn(format="%d점", min_value=0, max_value=100),
    "월간 검색량": st.column_config.NumberColumn(format="%d"),
    "월 블로그 발행": st.column_config.NumberColumn("월 블로그 발행", format="%d", help="최근 30일 새 블로그 글 수"),
    "월 카페 발행": st.column_config.NumberColumn("월 카페 발행(추정)", format="%d"),
    "월 전체 발행": st.column_config.NumberColumn(format="%d"),
    "블로그 포화(%)": st.column_config.NumberColumn(format="%.2f%%"),
    "카페 포화(%)": st.column_config.NumberColumn(format="%.2f%%"),
    "전체 포화(%)": st.column_config.NumberColumn(format="%.2f%%"),
}


# ---------------------------------------------------------------- 배포 모드 / 비밀번호
def _secrets() -> dict:
    """Streamlit Cloud 의 Secrets(비밀 설정). 내 PC 에서 실행할 때는 비어 있다."""
    try:
        return dict(st.secrets)
    except Exception:
        return {}


SECRETS = _secrets()
DEPLOYED = bool(SECRETS.get("NAVER_AD_API_KEY"))  # 클라우드에 키가 들어 있으면 '공용 사이트' 모드

if DEPLOYED and SECRETS.get("APP_PASSWORD"):
    if not st.session_state.get("authed"):
        st.markdown('<div class="kf-head"><b>🔑 KEYWORD FINDER</b><span>네이버 키워드 검색량 · 발행량 · 포화지수</span></div>',
                    unsafe_allow_html=True)
        with st.form("login"):
            pw = st.text_input("비밀번호", type="password", placeholder="관리자에게 받은 비밀번호를 입력하세요")
            if st.form_submit_button("들어가기", type="primary"):
                if pw == str(SECRETS["APP_PASSWORD"]):
                    st.session_state["authed"] = True
                    st.rerun()
                st.error("비밀번호가 틀렸습니다.")
        st.stop()


@st.cache_resource
def _shared_cache() -> dict:
    """모든 사용자가 함께 쓰는 결과 저장소 — 같은 키워드는 6시간 동안 다시 조회하지 않아 API 한도를 아낀다."""
    return {}


CACHE_TTL = 6 * 3600


def cached(kind: str, key: tuple, fn):
    import time as _t
    store = _shared_cache()
    k = (kind,) + key
    hit = store.get(k)
    if hit and _t.time() - hit[0] < CACHE_TTL:
        return hit[1]
    val = fn()
    store[k] = (_t.time(), val)
    if len(store) > 500:  # 오래된 것부터 정리
        for old in sorted(store, key=lambda x: store[x][0])[:100]:
            store.pop(old, None)
    return val


# ---------------------------------------------------------------- 사이드바
with st.sidebar:
    if DEPLOYED:
        ad_key, ad_secret, ad_cid = (str(SECRETS["NAVER_AD_API_KEY"]), str(SECRETS["NAVER_AD_SECRET_KEY"]),
                                     str(SECRETS["NAVER_AD_CUSTOMER_ID"]))
        cid, csec = str(SECRETS["NAVER_CLIENT_ID"]), str(SECRETS["NAVER_CLIENT_SECRET"])
        provider = str(SECRETS.get("NAVER_API_PROVIDER", "apihub"))
        st.caption("🌐 공용 사이트 · 같은 키워드는 6시간 동안 저장된 결과를 보여줍니다")
    else:
        env = load_env()
        keys_ready = all(env[k] for k in ["NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_AD_CUSTOMER_ID",
                                          "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"])
        with st.expander("🔐 API 키 설정", expanded=not keys_ready):
            st.markdown("**① 검색광고 API** (검색량)")
            ad_key = st.text_input("API 키 (액세스라이선스)", env["NAVER_AD_API_KEY"], type="password")
            ad_secret = st.text_input("비밀키", env["NAVER_AD_SECRET_KEY"], type="password")
            ad_cid = st.text_input("CUSTOMER_ID", env["NAVER_AD_CUSTOMER_ID"])
            st.markdown("**② 네이버 검색 API** (발행량)")
            providers = {"apihub": "NAVER API HUB (네이버 클라우드)", "developers": "네이버 개발자센터 (기존 키)"}
            provider = st.radio("발급받은 곳", list(providers), format_func=providers.get,
                                index=0 if env["NAVER_API_PROVIDER"] != "developers" else 1)
            cid = st.text_input("Client ID", env["NAVER_CLIENT_ID"], type="password")
            csec = st.text_input("Client Secret", env["NAVER_CLIENT_SECRET"], type="password")
            if st.button("💾 키 저장"):
                save_env({
                    "NAVER_AD_API_KEY": ad_key, "NAVER_AD_SECRET_KEY": ad_secret,
                    "NAVER_AD_CUSTOMER_ID": ad_cid, "NAVER_CLIENT_ID": cid, "NAVER_CLIENT_SECRET": csec,
                    "NAVER_API_PROVIDER": provider,
                })
                st.success("저장했습니다.")

    st.header("🏆 황금 키워드 추천 옵션")
    auto_disc = st.checkbox("검색할 때 자동으로 찾기", value=True)
    deep = st.checkbox("깊게 찾기 (연관의 연관까지)", value=True,
                       help="상위 연관 키워드 5개로 한 번 더 확장해 후보를 넓힙니다.")
    match_opts = {"first": "주제어(첫 단어) 포함", "all": "핵심 단어 모두 포함",
                  "any": "핵심 단어 하나라도 포함", "none": "거르지 않음"}
    match = st.radio("관련성 필터", list(match_opts), format_func=match_opts.get,
                     help="‘팔공산 맛집’ → 주제어 ‘팔공산’, 핵심 단어 ‘팔공산’·‘맛집’. "
                          "띄어쓰기가 없으면 자동으로 나눕니다.")
    min_volume = st.number_input("최소 월간 검색량", 0, 1_000_000, 100, step=50)
    max_keywords = st.slider("발행량을 조회할 후보 수", 10, 150, 40, step=10,
                             help="많을수록 넓게 찾지만 오래 걸립니다(40개 ≈ 30~60초).")
    count_recent = True  # 항상 한 달(최근 30일) 기준 — 블랙키위와 같은 방식
    st.header("📍 지역 키워드 옵션")
    auto_reg = st.checkbox("지역 키워드도 자동으로 찾기", value=True,
                           help="검색어에 ‘대구 동구’처럼 지역이 있으면 동네·다른 구 키워드를 함께 찾습니다.")
    max_hoods = st.slider("동네·명소 키워드 최대 개수", 10, 60, 30, step=5)

# ---------------------------------------------------------------- 검색창
st.markdown('<div class="kf-head"><b>🔑 KEYWORD FINDER</b><span>네이버 키워드 검색량 · 발행량 · 포화지수</span></div>',
            unsafe_allow_html=True)
if "pending_query" in st.session_state:
    st.session_state["q"] = st.session_state.pop("pending_query")
    st.session_state["auto_submit"] = True

with st.form("search", border=False):
    c1, c2 = st.columns([5, 1])
    query = c1.text_input("키워드", placeholder="분석할 키워드를 입력하고 Enter (예: 팔공산 맛집)",
                          label_visibility="collapsed", key="q")
    submitted = c2.form_submit_button("🔍 분석", type="primary", use_container_width=True)

if st.session_state.pop("auto_submit", False):
    submitted = True

if submitted:
    if not query.strip():
        st.warning("키워드를 입력해 주세요.")
        st.stop()
    if not all([ad_key, ad_secret, ad_cid, cid, csec]):
        st.error("API 키가 설정되지 않았습니다. (공용 사이트라면 관리자에게 문의하세요)" if DEPLOYED
                 else "왼쪽 ‘API 키 설정’에 키 5개를 입력하고 저장해 주세요.")
        st.stop()
    ad = SearchAdClient(ad_key, ad_secret, ad_cid)
    api = OpenApiClient(cid, csec, provider)
    try:
        with st.spinner(f"‘{query.strip()}’ 분석 중… (10~30초)"):
            detail = cached("detail", (query.strip(),), lambda: keyword_detail(ad, api, query.strip()))
    except Exception as e:
        st.error(f"오류: {type(e).__name__} {e}")
        st.stop()
    st.session_state["detail"] = detail
    st.session_state["disc_df"] = None
    st.session_state["disc_opts"] = None
    st.session_state["run_disc"] = auto_disc
    st.session_state["reg_out"] = None
    st.session_state["reg_opts"] = None
    st.session_state["run_reg"] = auto_reg

detail = st.session_state.get("detail")
if not detail:
    st.info("위 검색창에 키워드를 입력하면 블랙키위처럼 검색량·발행량·포화지수를 보여드립니다.")
    st.stop()

row = detail["row"]
tab1, tab2, tab4, tab3 = st.tabs(["기본 정보", "🏆 황금 키워드 추천", "📍 지역 키워드", "트렌드 분석"])

# ---------------------------------------------------------------- 탭1: 기본 정보
with tab1:
    st.markdown(f"### {escape(detail['keyword'])}")
    lvl_total, col_total = sat_level(detail["sat"]["전체"])
    g_color = {"A": "#12b886", "B": "#40c057", "C": "#fab005", "D": "#fd7e14", "E": "#fa5252"}[detail["grade"]]
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(mini("키워드 등급", detail["grade"], g_color), unsafe_allow_html=True)
    m2.markdown(mini("검색 광고 경쟁", row.get("광고 경쟁") or "-"), unsafe_allow_html=True)
    m3.markdown(mini("월평균 광고 클릭수", fmt(detail["clicks"])), unsafe_allow_html=True)
    m4.markdown(mini("모바일 검색 비중", f"{detail['mobile_share']:.0f}%"), unsafe_allow_html=True)
    st.write("")

    left, right = st.columns(2)
    with left:
        st.markdown(card("월간 검색량", [
            {"icon": "🖥️", "value": fmt(row["PC 검색량"]), "label": "PC"},
            {"icon": "📱", "value": fmt(row["모바일 검색량"]), "label": "Mobile"},
            {"icon": "➕", "value": fmt(row["월간 검색량"]), "label": "Total"},
        ], "최근 30일 · 검색광고 API"), unsafe_allow_html=True)

        mo = detail["month"]
        if mo.get("ok"):
            t1, c1_ = change_text(mo["mtd_change"])
            t2, c2_ = change_text(mo["projected_change"])
            st.markdown(card(f"{mo['month']}월 예상 검색량", [
                {"icon": "🔍", "value": fmt(mo["mtd"]), "label": f"{mo['month']}월 {mo['upto_day']}일까지 검색량",
                 "sub": t1, "sub_color": c1_},
                {"icon": "📊", "value": fmt(mo["projected"]),
                 "label": f"{mo['month']}월 {mo['days_in_month']}일까지 예상되는 검색량", "sub": t2, "sub_color": c2_},
            ], "데이터랩 일별 추이로 환산"), unsafe_allow_html=True)
        else:
            st.markdown(card("이번 달 예상 검색량", [
                {"icon": "🔍", "value": "-", "label": "검색어 트렌드 API가 필요합니다"},
            ]), unsafe_allow_html=True)

    with right:
        est = " (추정)" if detail["blog_est"] else ""
        st.markdown(card("월간 콘텐츠 발행량", [
            {"icon": "📝", "value": fmt(detail["blog_30"]), "label": f"블로그{est}"},
            {"icon": "☕", "value": fmt(detail["cafe_30"]), "label": "카페 (추정)"},
            {"icon": "📚", "value": fmt(detail["total_30"]), "label": "전체"},
        ], "최근 30일", note=f"누적 문서 수 · 블로그 {fmt(detail['blog_total'])} / 카페 {fmt(detail['cafe_total'])}"),
            unsafe_allow_html=True)

        items = []
        for name, icon in [("블로그", "📝"), ("카페", "☕"), ("전체", "📚")]:
            p = detail["sat"][name]
            lv, colr = sat_level(p)
            items.append({"icon": icon, "value": f"{p:.2f}%", "label": name, "sub": lv, "sub_color": colr})
        st.markdown(card("콘텐츠 포화 지수", items, "월간 발행량 ÷ 월간 검색량"), unsafe_allow_html=True)

    with st.expander("ℹ️ 지표 설명"):
        st.markdown(
            "- **월간 콘텐츠 발행량(블로그)**: 최근 30일 동안 발행된 블로그 글 수. 1,000건이 넘으면 최신 1,000건의 발행 속도로 환산합니다(추정).\n"
            "- **카페 발행량**: 카페 검색 결과에는 작성일이 없어, 블로그의 ‘최근 30일 비율’을 카페 누적 문서 수에 적용한 추정치입니다.\n"
            "- **포화 지수**: 낮을수록 검색 수요 대비 글이 적어 상위 노출에 유리합니다. "
            "10% 미만 매우 낮음 · 30% 미만 낮음 · 50% 미만 보통 · 70% 미만 높음 · 그 이상 매우 높음.\n"
            "- **키워드 등급**: 전체 포화 지수 기준 A(10% 미만)~E(150% 이상).\n"
            "- **예상 검색량**: 데이터랩 일별 상대값을 최근 30일 검색량에 맞춰 환산하고, 남은 날은 최근 7일 평균으로 채운 값입니다."
        )

# ---------------------------------------------------------------- 탭2: 황금 키워드 추천
with tab2:
    opts = (detail["keyword"], deep, match, min_volume, max_keywords, count_recent)
    fresh = st.session_state.get("disc_df") is not None and st.session_state.get("disc_opts") == opts
    if not fresh:
        if st.session_state.get("disc_opts") is not None:
            st.info("옵션이 바뀌었습니다. 다시 찾아 주세요.")
        run_now = st.session_state.pop("run_disc", False)
        if st.button("🏆 황금 키워드 찾기", type="primary") or run_now:
            bar = st.progress(0.0, text="연관 키워드 수집 중…")
            try:
                df, info = cached("disc", opts, lambda: discover(
                    SearchAdClient(ad_key, ad_secret, ad_cid), OpenApiClient(cid, csec, provider),
                    detail["keyword"], deep, match, min_volume, max_keywords, count_recent,
                    progress=lambda d, t: bar.progress(d / t, text=f"발행량 조회 중… {d}/{t}"),
                ))
            except Exception as e:
                bar.empty()
                st.error(f"오류: {type(e).__name__} {e}")
                st.stop()
            bar.empty()
            st.session_state["disc_df"], st.session_state["disc_info"] = df, info
            st.session_state["disc_opts"] = opts
            st.rerun()
        else:
            st.caption(f"‘{detail['keyword']}’와 관련된 키워드를 넓게 모아 검색량은 많고 발행량은 적은 순으로 추천합니다.")

    df = st.session_state.get("disc_df")
    info = st.session_state.get("disc_info", {})
    if fresh and df is not None:
        if df.empty:
            st.info("조건에 맞는 키워드가 없습니다. 최소 검색량을 낮추거나 관련성 필터를 ‘거르지 않음’으로 바꿔 보세요.")
        else:
            msg = (f"연관 키워드 {info.get('collected', 0)}개 수집 → 관련 {info.get('relevant', 0)}개 → "
                   f"검색량 상위 {info.get('checked', 0)}개 발행량 조회")
            if info.get("failed"):
                msg += f" · 조회 실패로 제외 {len(info['failed'])}개"
            st.caption(msg)
            toks = info.get("tokens", [])
            if toks:
                st.caption("핵심 단어: " + " · ".join(f"‘{t}’" for t in toks))
            if info.get("relaxed"):
                st.caption(f"⚠️ 관련 키워드가 5개 미만이라 필터를 ‘{match_opts[info['relaxed']]}’(으)로 넓혔습니다.")

            recs = df[~df["시드"]].head(12)
            html = rec_cards(recs.to_dict("records"))
            vars_ = [(k, v) for k, v in info.get("variants", []) if v > 0]
            if vars_:
                st.markdown("#### 🔁 비슷하게 검색하는 표현")
                st.caption("‘근처·주변·밥집·식당·추천’처럼 같은 뜻으로 바꿔 검색하는 표현 중 실제 검색량이 있는 것 (월간 검색량)")
                chips = "".join(f'<span class="kf-chip">{escape(k)}<b>{fmt(v)}</b></span>' for k, v in vars_[:24])
                st.markdown(f'<div class="kf-chips">{chips}</div>', unsafe_allow_html=True)
            st.markdown("#### 🏆 추천 키워드 TOP 12")
            st.caption("모든 숫자는 **한 달 기준**입니다 · 발행량 = 최근 30일 새 글 수 · 포화지수 = 월 발행량 ÷ 월 검색량 "
                       "(낮을수록 경쟁이 적음) · * 표시 = 글이 많아 발행 속도로 추정")
            st.markdown(html, unsafe_allow_html=True)

            s1, s2 = st.columns([4, 1])
            pick_kw = s1.selectbox("추천 키워드 자세히 보기", recs["키워드"].tolist(), label_visibility="collapsed")
            if s2.button("🔎 이 키워드 상세 분석", use_container_width=True):
                st.session_state["pending_query"] = pick_kw
                st.rerun()

            st.markdown("#### 전체 후보")
            show = ["추천점수", "경쟁도", "키워드", "출처"] + MONTH_COLS + ["광고 경쟁"]
            view = df[[c for c in show if c in df.columns]]
            f1, f2 = st.columns([2, 3])
            grades = [g for g in ["🟢 매우 낮음", "🟢 낮음", "🟡 보통", "🟠 높음", "🔴 매우 높음"]
                      if g in set(view["경쟁도"])]
            gp = f1.multiselect("경쟁도 필터", grades, default=grades)
            qq = f2.text_input("키워드 포함 검색", "")
            view = view[view["경쟁도"].isin(gp)]
            if qq:
                view = view[view["키워드"].str.contains(qq, case=False)]
            st.dataframe(view, use_container_width=True, hide_index=True, height=520, column_config=MONTH_CFG)
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ CSV 다운로드", view.to_csv(index=False).encode("utf-8-sig"),
                               f"{detail['keyword']}_황금키워드.csv", "text/csv")
            buf = io.BytesIO()
            view.to_excel(buf, index=False, sheet_name="황금키워드")
            d2.download_button("⬇️ 엑셀 다운로드", buf.getvalue(), f"{detail['keyword']}_황금키워드.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with st.expander("ℹ️ 추천점수 계산 방법"):
                st.markdown(
                    "- **추천점수(100점)** = 검색량 점수(50) + 경쟁 점수(50)\n"
                    "- 검색량 점수: 월 1천 회=30점, 1만 회=40점, 10만 회 이상=50점\n"
                    "- 경쟁 점수: 검색량 대비 글이 적을수록 높음 (포화지수 0%=50점)\n"
                    "- 그래서 **찾는 사람은 꽤 많은데 글은 적은** 키워드가 위로 올라옵니다."
                )

# ---------------------------------------------------------------- 탭4: 지역 키워드
with tab4:
    reg = parse_region(detail["keyword"])
    if reg and not reg["category"]:
        st.info("지역 뒤에 업종을 붙여 검색해 주세요. 예) ‘대구 동구 맛집’, ‘수성구 카페’, ‘팔공산 맛집’")
    else:
        if reg:
            st.caption(f"📍 인식된 지역: **{region_label(reg)}** · 업종: **{reg['category']}**")
        else:
            st.caption("📍 검색어에 행정구역 이름이 없어, 블로그 언급으로 어느 지역인지 찾아봅니다.")
        ropts = (detail["keyword"], min_volume, max_hoods, count_recent)
        rfresh = st.session_state.get("reg_out") is not None and st.session_state.get("reg_opts") == ropts
        if not rfresh:
            run_now = st.session_state.pop("run_reg", False)
            if st.button("📍 지역 키워드 찾기", type="primary") or run_now:
                bar = st.progress(0.0, text="지역 확인·동네 키워드 수집 중… (1~3분)")
                try:
                    out = cached("region", ropts, lambda: discover_region(
                        SearchAdClient(ad_key, ad_secret, ad_cid), OpenApiClient(cid, csec, provider),
                        detail["keyword"], min(min_volume, 50), max_hoods, count_recent,
                        progress=lambda d, t: bar.progress(d / t, text=f"동네 확인·발행량 조회 중… {d}/{t}"),
                    ))
                except Exception as e:
                    bar.empty()
                    st.error(f"오류: {type(e).__name__} {e}")
                    st.stop()
                bar.empty()
                st.session_state["reg_out"] = out if out is not None else {"region": None}
                st.session_state["reg_opts"] = ropts
                st.rerun()

        out = st.session_state.get("reg_out")
        if rfresh and out is not None and out.get("region") is None:
            st.info(f"‘{out.get('anchor', detail['keyword'])}’이(가) 어느 지역인지 판단하기 어렵습니다 "
                    "(여러 지역에 흔한 이름일 수 있어요). ‘대구 동구 맛집’처럼 지역을 넣어 검색해 보세요.")
        elif rfresh and out is not None:
            reg = out["region"]
            if reg.get("anchor"):
                st.success(f"📍 ‘{reg['anchor']}’ → **{region_label(reg)}**(으)로 인식했습니다 · 업종: **{reg['category']}**")
            rdf = out["df"]
            if rdf.empty:
                st.info("지역 키워드를 찾지 못했습니다.")
            else:
                cat = reg["category"]
                where = reg["gu"] or reg["sido"]

                hoods = rdf[rdf["구분"] == "동네·명소"]
                st.markdown(f"#### 🏘️ {where} 동네·명소 {cat} 키워드")
                if hoods.empty:
                    st.caption("연관 키워드에서 동네 이름을 찾지 못했습니다.")
                else:
                    st.caption(f"{len(hoods)}개 확인 · 추천점수 순 · 카드 위 이름 = 동네·명소, 아래 = 실제 검색 키워드 · "
                               "* 표시 = 글이 많아 발행 속도로 추정")
                    st.markdown(rec_cards(hoods.head(12).to_dict("records"), name_col="지역", rank_label="동네"),
                                unsafe_allow_html=True)

                if out.get("rejected"):
                    st.caption(f"🚫 다른 지역으로 판단해 뺀 곳: {', '.join(out['rejected'][:20])}")
                if out.get("metrics"):
                    with st.expander("🔬 동네 판정 상세 (블로그 함께 언급 수)"):
                        st.table(pd.DataFrame(out["metrics"]))

                comp = rdf[rdf["구분"] != "동네·명소"].copy()
                if not comp.empty:
                    st.markdown(f"#### 🗺️ {reg['sido']} 구·군별 ‘{cat}’ 비교")
                    best_row = comp.iloc[0]
                    st.caption(f"가장 추천: **{best_row['지역']}** ({best_row['키워드']}, {best_row['추천점수']}점)"
                               + ("" if best_row["구분"] == "내 지역" else " · 내 지역보다 기회가 큽니다"))
                    comp["지역 "] = comp.apply(lambda x: f"⭐ {x['지역']}" if x["구분"] == "내 지역" else x["지역"], axis=1)
                    st.bar_chart(comp.set_index("지역 ")[["월간 검색량"]], height=260, horizontal=True)
                    st.dataframe(comp[["추천점수", "경쟁도", "지역 ", "키워드"] + MONTH_COLS],
                                 use_container_width=True, hide_index=True, column_config=MONTH_CFG)

                s1, s2 = st.columns([4, 1])
                pick_kw = s1.selectbox("지역 키워드 자세히 보기", rdf["키워드"].tolist(), label_visibility="collapsed",
                                       key="reg_pick")
                if s2.button("🔎 상세 분석", use_container_width=True, key="reg_go"):
                    st.session_state["pending_query"] = pick_kw
                    st.rerun()

                cols = ["추천점수", "경쟁도", "구분", "지역", "키워드"] + MONTH_COLS
                full = rdf[[c for c in cols if c in rdf.columns]]
                buf = io.BytesIO()
                full.to_excel(buf, index=False, sheet_name="지역키워드")
                st.download_button("⬇️ 지역 키워드 엑셀 다운로드", buf.getvalue(), f"{detail['keyword']}_지역키워드.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                st.caption("※ 동네·명소는 네이버 연관 키워드에서 골라낸 뒤, 블로그에서 ‘지역+동네’가 함께 언급되는 횟수로 "
                           "내 지역 것인지 확인했습니다. 경계에 걸친 곳은 섞이거나 빠질 수 있습니다.")

# ---------------------------------------------------------------- 탭3: 트렌드
with tab3:
    if detail["trend_error"]:
        st.warning("검색어 트렌드를 불러오지 못했습니다. 네이버 클라우드 API HUB의 Application에 "
                   f"‘검색어 트렌드’ API가 추가되어 있는지 확인하세요.\n\n{detail['trend_error']}")
    else:
        vol = row["월간 검색량"]
        tr = pd.DataFrame(detail["trend"])
        if not tr.empty:
            # 상대값(최대 100)을 최근 달 = 최근 30일 검색량 기준으로 환산
            # 이번 달은 진행 중이라 값이 작으므로, 직전 완료 월을 최근 30일 검색량에 맞춘다
            ref = tr["ratio"].iloc[-2] if len(tr) >= 2 else tr["ratio"].iloc[-1]
            last = ref or tr["ratio"].max()
            tr["추정 검색량"] = (tr["ratio"] / last * vol).round()
            tr["월"] = tr["period"].str[:7]
            st.subheader("월별 검색량 추이 (최근 12개월)")
            st.bar_chart(tr.set_index("월")["추정 검색량"], height=320)
        mo = detail["month"]
        if mo.get("ok"):
            st.subheader("일별 검색량 추이 (최근 60일)")
            st.line_chart(pd.DataFrame(mo["daily"]).set_index("날짜"), height=300)
        st.caption("데이터랩 상대값을 검색광고 API 검색량에 맞춰 환산한 추정치입니다. "
                   "이번 달은 진행 중이라 월별 막대가 작게 보일 수 있습니다.")
