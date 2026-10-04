@echo off
rem Start PaperBrief on 127.0.0.1 and open the browser. Needs uv (https://docs.astral.sh/uv/).
cd /d "%~dp0"
uv run python -m paperbrief
if errorlevel 1 pause
