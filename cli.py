"""
화면 없이 바로 엑셀로 뽑는 명령줄 버전.

예)
  python cli.py "팔공산 맛집"                 → 기본 정보 + 황금 키워드 추천 → 엑셀
  python cli.py "대구 동구 맛집" --region     → 지역 키워드(동네·다른 구 비교)까지
  python cli.py 캠핑의자 차박용품 --legacy    → 예전 방식: 여러 시드의 연관 키워드 표
옵션
  --min 100      최소 월간 검색량
  --max 40       발행량을 조회할 후보 수
  -o 결과.xlsx   저장 파일 이름 (기본: '<키워드>_키워드분석.xlsx')
"""

import argparse
import sys

import pandas as pd

from analyzer import discover, discover_region, keyword_detail, run
from config import load_env
from naver_api import OpenApiClient, SearchAdClient

MONTH_COLS = ["추천점수", "경쟁도", "키워드", "월간 검색량", "PC 검색량", "모바일 검색량",
              "월 블로그 발행", "월 카페 발행", "월 전체 발행", "블로그 포화(%)", "카페 포화(%)", "전체 포화(%)"]


def progress(done, total):
    print(f"\r  발행량 조회 {done}/{total}", end="", flush=True)


def main():
    p = argparse.ArgumentParser(description="네이버 키워드분석 프로그램 (명령줄)")
    p.add_argument("keywords", nargs="+", help="분석할 키워드 (띄어쓰기 있으면 따옴표로 감싸기)")
    p.add_argument("--min", type=int, default=100, help="최소 월간 검색량 (기본 100)")
    p.add_argument("--max", type=int, default=40, help="발행량을 조회할 후보 수 (기본 40)")
    p.add_argument("--region", action="store_true", help="지역 키워드(동네·다른 구 비교)도 찾기")
    p.add_argument("--legacy", action="store_true", help="예전 방식: 여러 시드 → 연관 키워드 표")
    p.add_argument("-o", "--output", default=None, help="저장 파일 (.xlsx)")
    a = p.parse_args()

    env = load_env()
    need = ["NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_AD_CUSTOMER_ID", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"]
    missing = [k for k in need if not env.get(k)]
    if missing:
        sys.exit(f".env 에 다음 값을 채워 주세요: {', '.join(missing)}")
    ad = SearchAdClient(env["NAVER_AD_API_KEY"], env["NAVER_AD_SECRET_KEY"], env["NAVER_AD_CUSTOMER_ID"])
    api = OpenApiClient(env["NAVER_CLIENT_ID"], env["NAVER_CLIENT_SECRET"], env["NAVER_API_PROVIDER"])

    if a.legacy:
        df = run(ad, api, a.keywords, a.min, a.max, count_recent=True, progress=progress)
        out = a.output or "keywords.xlsx"
        df.to_excel(out, index=False, sheet_name="키워드")
        print(f"\n✅ {len(df)}개 키워드 저장 → {out}")
        return

    query = " ".join(a.keywords)
    out = a.output or f"{query.replace(' ', '_')}_키워드분석.xlsx"
    sheets: dict[str, pd.DataFrame] = {}

    print(f"① 기본 정보: {query}")
    d = keyword_detail(ad, api, query)
    r = d["row"]
    sheets["기본정보"] = pd.DataFrame([{
        "키워드": query, "PC 검색량": r["PC 검색량"], "모바일 검색량": r["모바일 검색량"], "월간 검색량": r["월간 검색량"],
        "월 블로그 발행": d["blog_30"], "월 카페 발행(추정)": d["cafe_30"], "월 전체 발행": d["total_30"],
        "블로그 포화(%)": round(d["sat"]["블로그"], 2), "카페 포화(%)": round(d["sat"]["카페"], 2),
        "전체 포화(%)": round(d["sat"]["전체"], 2), "키워드 등급": d["grade"], "광고 경쟁": r.get("광고 경쟁"),
    }])
    print(f"   월간 검색량 {r['월간 검색량']:,} · 월 발행 {d['total_30']:,} · 포화 {d['sat']['전체']:.2f}% · 등급 {d['grade']}")

    print("② 황금 키워드 추천")
    df, info = discover(ad, api, query, True, "first", a.min, a.max, True, progress=progress)
    print()
    if not df.empty:
        sheets["황금키워드"] = df[[c for c in MONTH_COLS + ["출처"] if c in df.columns]]
        for _, x in df[~df["시드"]].head(10).iterrows():
            print(f"   {x['추천점수']:>3}점  {x['키워드']:<20} 검색 {x['월간 검색량']:>7,}  월발행 {x['월 전체 발행']:>6,}  {x['경쟁도']}")
    if info.get("variants"):
        sheets["비슷한표현"] = pd.DataFrame(info["variants"], columns=["키워드", "월간 검색량"])

    if a.region:
        print("③ 지역 키워드 (2~3분)")
        res = discover_region(ad, api, query, min(a.min, 50), 30, True, progress=progress)
        print()
        if res and res.get("region") and not res["df"].empty:
            rdf = res["df"]
            sheets["지역키워드"] = rdf[[c for c in ["구분", "지역"] + MONTH_COLS if c in rdf.columns]]
            print(f"   지역: {res['region']['sido']} {res['region'].get('gu') or ''} · {len(rdf)}개")
        else:
            print("   지역을 인식하지 못했습니다.")

    with pd.ExcelWriter(out) as w:
        for name, sdf in sheets.items():
            sdf.to_excel(w, index=False, sheet_name=name)
    print(f"✅ 저장 → {out}")


if __name__ == "__main__":
    main()
