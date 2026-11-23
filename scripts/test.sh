#!/usr/bin/env bash
# 文件用途：隔离宿主机外部 pytest 插件，运行算法验证区的离线回归检查。
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT/algorithm-lab"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH= "$PROJECT_ROOT/.venv/bin/python3" -m pytest -q "$@"
node --check web/app.js
node --check web/video-inspection.js
