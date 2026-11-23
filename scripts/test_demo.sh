#!/usr/bin/env bash
# 文件用途：运行网页 Demo 后端 pytest 回归、前端 Vitest 单元测试、类型检查与生产构建验证。
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/4] 运行后端接口与恢复回归测试..."
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PROJECT_ROOT/web-demo/backend" \
  "$PROJECT_ROOT/.venv/bin/python3" -m pytest -q "$PROJECT_ROOT/web-demo/backend/tests"

echo "[2/4] 运行前端 Vitest 单元测试..."
(cd "$PROJECT_ROOT/web-demo/frontend" && npm run test)

echo "[3/4] 运行前端 TypeScript 类型检查..."
(cd "$PROJECT_ROOT/web-demo/frontend" && npm run typecheck)

echo "[4/4] 验证前端生产构建..."
(cd "$PROJECT_ROOT/web-demo/frontend" && npm run build)

echo "网页 Demo 全部离线检查通过。"
