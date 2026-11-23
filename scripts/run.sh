#!/usr/bin/env bash
# 文件用途：从仓库根入口在本机回环地址启动算法验证网页。
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT/algorithm-lab"
if [[ ! -x "$PROJECT_ROOT/.venv/bin/python3" ]]; then
  echo "请在仓库根目录执行 python3 -m venv .venv，再用 .venv/bin/python3 -m pip install -r algorithm-lab/requirements.txt 安装依赖。"
  exit 1
fi
exec env PYTHONPATH= "$PROJECT_ROOT/.venv/bin/python3" -m uvicorn app.main:app --host 127.0.0.1 --port "${PET_PORT:-8000}" --workers 1
