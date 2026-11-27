"""API 키를 .env 파일 또는 환경변수에서 읽는다 (추가 패키지 없이)."""

import os
from pathlib import Path

KEYS = [
    "NAVER_AD_API_KEY",
    "NAVER_AD_SECRET_KEY",
    "NAVER_AD_CUSTOMER_ID",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "NAVER_API_PROVIDER",
]
# 화면의 '키 저장'에서는 다루지 않지만 .env 에 적어 두면 읽는 값 (결과 기록용 Supabase)
EXTRA_KEYS = ["SUPABASE_URL", "SUPABASE_KEY"]


def load_env(path: str | Path = Path(__file__).parent / ".env") -> dict:
    values = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    for k in KEYS + EXTRA_KEYS:
        values.setdefault(k, os.environ.get(k, ""))
    if not values["NAVER_API_PROVIDER"]:
        values["NAVER_API_PROVIDER"] = "apihub"
    return values


def save_env(values: dict, path: str | Path = Path(__file__).parent / ".env") -> None:
    lines = [f"{k}={values.get(k, '')}" for k in KEYS]
    p = Path(path)
    if p.exists():  # 화면에서 다루지 않는 줄(SUPABASE_* 등)은 지우지 않고 그대로 둔다
        for line in p.read_text(encoding="utf-8").splitlines():
            k = line.split("=", 1)[0].strip()
            if "=" in line and not line.strip().startswith("#") and k not in KEYS:
                lines.append(line.strip())
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
