"""
조회 결과를 Supabase 표(kw_results)에 쌓아 둔다.

- 주소와 키는 SUPABASE_URL / SUPABASE_KEY (Streamlit Secrets 또는 .env).
  둘 중 하나라도 없으면 아무것도 하지 않는다.
- 키는 공개용(publishable/anon) 키를 쓴다. 이 표에는 '추가'만 허용돼 있어서,
  키가 새어도 기록을 읽거나 지울 수는 없다. 기록은 Supabase 대시보드에서 본다.
- 저장은 뒤에서(별도 스레드) 하므로 화면이 느려지지 않고, 실패해도 분석에는 영향이 없다.
"""

import json
import math
import threading

import pandas as pd
import requests

TABLE = "kw_results"


def _num(v, cast=float):
    try:
        if v is None or pd.isna(v):
            return None
        return cast(v)
    except (TypeError, ValueError):
        return None


def _clean(o):
    """numpy 숫자·NaN 등을 JSON 으로 보낼 수 있는 값으로 바꾼다."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):  # numpy 숫자
        o = o.item()
    if isinstance(o, float) and math.isnan(o):
        return None
    if o is None or isinstance(o, (str, int, float, bool)):
        return o
    return str(o)


def rows_from_detail(detail: dict) -> list[dict]:
    row = detail["row"]
    sat = detail["sat"]["전체"]
    data = {
        **row,
        "블로그 누적 발행량": detail["blog_total"], "카페 누적 발행량": detail["cafe_total"],
        "월 블로그 발행": detail["blog_30"], "월 카페 발행": detail["cafe_30"],
        "블로그 포화(%)": round(detail["sat"]["블로그"], 2), "카페 포화(%)": round(detail["sat"]["카페"], 2),
        "등급": detail["grade"], "연관 키워드 수": len(detail.get("related") or []),
    }
    if detail.get("month", {}).get("ok"):
        data["이번 달 예상"] = detail["month"]
    return [{
        "kind": "기본 정보", "seed_keyword": detail["keyword"], "keyword": detail["keyword"],
        "monthly_volume": _num(row.get("월간 검색량"), int), "monthly_posts": _num(detail["total_30"], int),
        "saturation": round(sat, 2), "competition": detail["grade"], "score": None, "region": None,
        "data": _clean(data),
    }]


def rows_from_table(kind: str, seed: str, df: pd.DataFrame | None, region: str | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    out = []
    for rec in json.loads(df.to_json(orient="records", force_ascii=False)):
        out.append({
            "kind": kind, "seed_keyword": seed, "keyword": rec.get("키워드", ""),
            "monthly_volume": _num(rec.get("월간 검색량"), int), "monthly_posts": _num(rec.get("월 전체 발행"), int),
            "saturation": _num(rec.get("포화지수(%)")), "competition": rec.get("경쟁도"),
            "score": _num(rec.get("추천점수"), int), "region": rec.get("지역") or region,
            "data": rec,
        })
    return out


def _post(url: str, key: str, rows: list[dict]) -> None:
    try:
        r = requests.post(
            f"{url.rstrip('/')}/rest/v1/{TABLE}", json=rows, timeout=15,
            headers={"apikey": key, "Content-Type": "application/json", "Prefer": "return=minimal"},
        )
        if r.status_code >= 300:
            print(f"[supabase] 저장 실패 {r.status_code}: {r.text[:200]}")
    except Exception as e:  # 저장이 안 돼도 분석 화면은 계속 동작해야 한다
        print(f"[supabase] 저장 실패: {type(e).__name__} {e}")


def save(settings: dict, rows: list[dict], wait: bool = False) -> bool:
    """rows 를 저장한다. 주소·키가 없거나 rows 가 비면 False."""
    url, key = str(settings.get("SUPABASE_URL") or ""), str(settings.get("SUPABASE_KEY") or "")
    if not (url and key and rows):
        return False
    if wait:
        _post(url, key, rows)
    else:
        threading.Thread(target=_post, args=(url, key, rows), daemon=True).start()
    return True
