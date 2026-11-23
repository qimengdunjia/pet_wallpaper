#!/usr/bin/env bash
# 文件用途：从仓库根目录启动同源网页 Demo 服务（默认 127.0.0.1:8080，单 worker）。
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$PROJECT_ROOT/.venv/bin/python3" ]]; then
  echo "请在仓库根目录创建虚拟环境并安装依赖："
  echo "  python3 -m venv .venv && .venv/bin/python3 -m pip install -r web-demo/backend/requirements.txt"
  exit 1
fi

if [[ ! -f "$PROJECT_ROOT/web-demo/frontend/dist/index.html" ]]; then
  if [[ -d "$PROJECT_ROOT/web-demo/frontend/node_modules" ]]; then
    echo "未检测到前端构建产物，正在执行 npm run build..."
    (cd "$PROJECT_ROOT/web-demo/frontend" && npm run build)
  else
    echo "提示：尚未构建前端静态文件（web-demo/frontend/dist）。"
    echo "可先执行：cd web-demo/frontend && npm install && npm run build"
  fi
fi

cd "$PROJECT_ROOT/web-demo/backend"
exec env PYTHONPATH= "$PROJECT_ROOT/.venv/bin/python3" -m uvicorn app.main:app --host 127.0.0.1 --port "${DEMO_PORT:-8080}" --workers 1
