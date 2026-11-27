@echo off
chcp 65001 >nul
cd /d %~dp0
python tests\test_all.py
pause
