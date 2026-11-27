@echo off
chcp 65001 >nul
title 네이버 키워드분석 프로그램 - 이 창을 닫으면 프로그램이 꺼집니다
cd /d %~dp0
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  (echo [general]& echo email = "") > "%USERPROFILE%\.streamlit\credentials.toml"
)
if not exist .env (
  echo [안내] .env 파일이 없습니다. 화면 왼쪽 'API 키 설정'에서 키를 입력하고 저장하세요.
)
echo 필요한 프로그램을 확인하는 중입니다...
python -m pip install -r requirements.txt -q --no-warn-script-location
start "" cmd /c "timeout /t 6 >nul & start http://localhost:8501"
python -m streamlit run app.py --server.headless true --browser.gatherUsageStats false
pause
