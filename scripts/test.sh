#!/usr/bin/env bash
# 文件用途：隔离宿主机 ROS 等外部 pytest 插件，运行本项目离线回归检查。
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH= .venv/bin/python3 -m pytest -q "$@"
node --check web/app.js
node --check web/video-inspection.js
