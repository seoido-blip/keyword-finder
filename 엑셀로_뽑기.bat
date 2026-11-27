@echo off
chcp 65001 >nul
cd /d %~dp0
set /p KW=분석할 키워드를 입력하세요 (예: 팔공산 맛집): 
python cli.py "%KW%"
pause
