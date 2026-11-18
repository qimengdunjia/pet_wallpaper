#!/usr/bin/env bash
# 文件用途：使用项目虚拟环境，以单进程在本机回环地址启动网页 Demo。
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
if [[ ! -x .venv/bin/python3 ]]; then
  echo "请先执行 python3 -m venv .venv，再用 .venv/bin/python3 -m pip install -r requirements.txt 安装依赖。"
  exit 1
fi
exec env PYTHONPATH= .venv/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${PET_PORT:-8000}" --workers 1
