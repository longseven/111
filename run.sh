#!/usr/bin/env bash
# 一键本地启动：建虚拟环境 → 装依赖 → 读 .env → 起服务
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "==> 创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> 安装依赖 ..."
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "已生成 .env，请用编辑器打开填入你的 API key（provider 与 key），保存后再次运行 ./run.sh"
  echo "  路径：$(pwd)/.env"
  exit 1
fi

echo
echo "==> 启动服务： http://127.0.0.1:8000   （Ctrl+C 退出）"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
