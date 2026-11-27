# CLAUDE.md — 네이버 키워드분석 프로그램 개발 안내

사용자는 한국어로 소통하는 비개발자 마케터다. **설명과 화면 문구는 쉬운 한국어로 쓴다.** 수정하면 반드시 `python tests/test_all.py`를 돌린다.

## 구조
- `app.py` — Streamlit 화면. 탭 4개(기본 정보 / 🏆 황금 키워드 추천 / 📍 지역 키워드 / 트렌드 분석)
- `analyzer.py` — 분석 로직 (화면과 분리, `cli.py`와 함께 씀)
  - `enrich_with_documents`: 월 발행량·포화지수·경쟁도
  - `keyword_detail`: 기본 정보 + 이번 달 예상 검색량
  - `discover`: 황금 키워드
  - `discover_region`: 지역 키워드
- `naver_api.py` — `SearchAdClient`(검색광고 keywordstool, HMAC 서명) / `OpenApiClient`(블로그·카페 검색, 검색어 트렌드)
- `region.py` — 시·도 → 시·군·구 표(2026 기준, 대구 군위군·인천 제물포/영종/검단구 포함), `parse_region`, `extract_neighborhoods`
- `config.py` — `.env` 읽기/쓰기 (로컬 전용). `save_env`는 `SUPABASE_*`처럼 화면에서 안 다루는 줄을 지우지 않는다.
- `storage.py` — 새로 조회한 결과를 Supabase `kw_results` 표에 쌓는다 (`SUPABASE_URL`/`SUPABASE_KEY`가 있을 때만)
  - 프로젝트: `seoido-blip's Project` (ziltjzkrmltmckeqkohy). 다른 앱 표와 같이 쓰므로 이 앱 표는 `kw_` 로 시작한다.
  - 공개 키(anon)에는 INSERT만 허용. SELECT·수정·삭제는 막혀 있다.
  - `app.py`의 `remembered()`가 `cached()` 안에서 불려서, 6시간 캐시에서 꺼낼 때는 다시 쌓지 않는다.

## 외부 API와 제약 (중요)
- **검색광고 API** `https://api.searchad.naver.com/keywordstool`
  - 힌트는 최대 5개이고 **공백을 허용하지 않는다** (붙여서 보냄).
  - 검색량이 10 미만이면 `"< 10"`이 오는데, 5로 처리한다.
- **NAVER API HUB** (`provider="apihub"`, 기본값)
  - 주소: `https://naverapihub.apigw.ntruss.com` — `/search/v1/blog`, `/search/v1/cafearticle`, `/search-trend/v1/search`
  - 인증 헤더: `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY`
  - 2026-07-31부터 개발자센터의 검색 API 신규 발급이 중단됐다. 기존 키(`provider="developers"`, openapi.naver.com)는 2027-06-30까지 동작한다.
- 블로그 검색 한도:
  - `start`는 최대 1,000 → 날짜순으로 최대 1,000건까지만 볼 수 있다.
  - 하루 25,000회.
  - 429나 5xx 응답은 `_search`에서 최대 4번 다시 시도한다.
- 카페 검색 결과에는 **작성일이 없다** → 월 카페 발행량은 블로그 비율로 추정하고, 그 비율은 최대 20%로 제한한다.

## 핵심 계산 규칙 (실데이터로 맞춘 값 — 바꿀 때 주의)
- 월 블로그 발행:
  - 날짜순으로 30일 안의 글을 센다.
  - 1,000건이 넘으면 `count × 30 / 경과일(소수)`로 추정한다.
  - 결과가 누적 문서 수를 넘지 않게 자른다.
- 포화지수 = 월 발행 ÷ 월 검색 × 100.
  - `sat_level`: 10/30/50/70% 기준으로 매우 낮음~매우 높음.
  - 팔공산갓바위로 검증했다 (블랙키위와 일치).
- 추천점수 = `50·min(1, log10(검색량)/5) + 50/(1 + 포화/30)`.
- 조회에 실패한 키워드(`오류` 칸이 있음)는 추천에서 **빼야 한다.** 빼지 않으면 0으로 잡혀 1위가 되는 버그가 있었다.
- **동네 판정** (`verify_neighborhoods`, 대구 동구 실측으로 맞춤):
  - ① '시도 X' ÷ 'X' ≥ 20%. 키워드에 시도명이 붙어 있으면 8%, 시도만 입력했으면 30%.
  - ② 구까지 입력했다면: '시도 내구 X'가 다른 구 중 최다 대비 90% 이상이고, 'X' 전체의 5% 이상.
  - 마산, 진해, 왜관, 언양, 조치원, 동성로(중구) 같은 오판을 이 기준으로 걸렀다.
- **명소 지역 추정** (`infer_region`):
  - 17개 시·도 중 '시도 X'가 가장 많고, 단독 대비 15% 이상이며, 2위의 1.3배 이상이어야 채택한다.
  - 구도 같은 방식으로 정한다 (예: 팔공산 → 대구 동구).
- **비슷한 표현**: `CATEGORY_SYNONYMS`, `LOCATION_MODIFIERS`, `SUFFIX_MODIFIERS`. 업종을 추가할 때는 여기를 고친다.

## Streamlit 주의점 (실제로 겪은 문제)
- **진행 막대는 메인 스레드에서만 갱신한다.** ThreadPoolExecutor 안에서 `bar.progress`를 부르면 빈 메시지 예외가 난다.
- **브라우저 자동 번역**(엣지/크롬)이 화면을 바꾸면 `NotFoundError: removeChild`가 난다. `app.py` 맨 위의 `<html lang="ko" translate="no">` 주입 코드를 지우지 말 것.
- `app.py`는 실행할 때마다 `importlib.reload`로 하위 모듈을 다시 읽는다. 파일을 고친 뒤 F5만 누르면 반영된다.
- 배포 모드:
  - Secrets에 키가 있으면 `DEPLOYED`가 된다 → 비밀번호(`APP_PASSWORD`) 화면이 나오고, 키 입력 칸은 숨긴다.
  - Secrets의 `ENV = """…"""`에 .env 내용을 통째로 넣어도 읽는다.
  - **클라우드인데 키가 없으면 키 입력 칸을 보여 주지 말고 멈춘다.** 방문자가 서버의 .env를 덮어쓸 수 있기 때문.
- `cached()`(st.cache_resource 위의 dict)는 같은 키워드 결과를 6시간 동안 모든 사용자가 함께 쓴다 → API 한도 절약.

## 배포
- GitHub: `seoido-blip/keyword-finder` (public, main 브랜치)
  - 푸시하면 Streamlit Community Cloud(https://naver-keyword-finder.streamlit.app)가 1~2분 안에 자동 반영한다.
- 키와 비밀번호는 Streamlit 앱 **Settings → Secrets**에만 둔다. 저장소에 `.env`를 올리지 않는다 (`.gitignore`).
- Python 3.12, `requirements.txt` (streamlit≥1.37 — `bar_chart(horizontal=True)` 때문).

## Windows 실행
- `실행.bat`: `python -m pip`, `python -m streamlit`을 쓴다.
  - Scripts 폴더가 PATH에 없을 수 있어서다.
- 첫 실행 때 Streamlit이 이메일을 묻지 않도록 `%USERPROFILE%\.streamlit\credentials.toml`을 미리 만든다.
- bat 파일은 CRLF로 쓰고, 리디렉션은 `>nul`로 쓴다.
