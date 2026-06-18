@echo off
REM 一键本地启动（Windows）：建虚拟环境 -> 装依赖 -> 读 .env -> 起服务
cd /d "%~dp0"

if not exist .venv (
  echo ==^> 创建虚拟环境 .venv ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo ==^> 安装依赖 ...
pip install -q -r requirements.txt

if not exist .env (
  copy .env.example .env >nul
  echo.
  echo 已生成 .env，请用编辑器打开填入你的 API key 后再次运行 run.bat
  echo   路径：%cd%\.env
  pause
  exit /b 1
)

echo.
echo ==^> 启动服务： http://127.0.0.1:8000   ^(Ctrl+C 退出^)
uvicorn app.main:app --host 127.0.0.1 --port 8000
