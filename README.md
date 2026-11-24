<!-- 文件用途：提供宠物壁纸网页 Demo 与算法验证的仓库入口。 -->

# 宠物交互壁纸

面向横屏车机浏览器的宠物交互壁纸演示项目，支持猫狗录入、先导与追逐等待过场、16:9 三热区互动、多宠切换与刷新恢复；同时包含可独立运行的算法验证与素材生产工具。

## 目录结构

| 目录 | 用途 |
| --- | --- |
| [`web-demo/frontend/`](web-demo/frontend/README.md) | 基于 Vue 3 + TypeScript + Vite 的横屏网页交互、MasterGo 界面素材与视频播放 |
| [`web-demo/backend/`](web-demo/backend/README.md) | 基于 FastAPI + SQLite 的同源后端，提供档案管理、异步生成、Range 媒体流与状态恢复 |
| [`web-demo/assets/`](web-demo/assets/README.md) | 公共过场（3 秒先导、7 秒追逐循环）、预置默认狗狗壁纸与猫狗样例素材 |
| [`algorithm-lab/`](algorithm-lab/README.md) | 可灵网页验证、ComfyUI 宠物加载动画工作流、素材实验与离线回归 |
| [`docs/`](docs/网页Demo开发文档.md) | 产品需求、网页 Demo 架构方案与验收文档 |
| `scripts/` | 从仓库根目录启动与校验网页 Demo 及算法验证工具的脚本 |

开发与验收细节见[网页 Demo 开发文档](docs/网页Demo开发文档.md)，行为与素材规格以 [PRD](docs/宠物交互壁纸_PRD.md) 为准，页面流程与视觉设计参考[原型图](docs/原型图.jpg)和 [MasterGo「页面 1」](https://mastergo.com/prototyping/210826940496035?fileOpenFrom=project&page_id=M)。

## 网页 Demo

同源服务默认运行在 `http://127.0.0.1:8080`（可通过 `DEMO_PORT` 调整），默认使用 `mock` 模拟供应商，无需外部密钥即可体验完整流程。

### 首次准备

在仓库根目录创建 `.venv` 并安装后端依赖、构建前端产物：

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -r web-demo/backend/requirements.txt
cp -n web-demo/backend/.env.example web-demo/backend/.env

cd web-demo/frontend
npm install
npm run build
cd ../..
```

> 网页 Demo 底栏的齿轮可解锁生成设置，切换 Mock、ComfyUI 或可灵并编辑猫狗动作提示词。密码、ComfyUI 地址和可灵密钥的配置见[后端说明](web-demo/backend/README.md)。

### 启动与离线验证

从仓库根目录执行：

```bash
bash scripts/run_demo.sh   # 启动同源网页 Demo 服务（默认 127.0.0.1:8080）
bash scripts/test_demo.sh  # 运行后端 pytest、前端 Vitest、类型检查与生产构建验证
```

本地前端开发时可另启 `cd web-demo/frontend && npm run dev`（端口 `5173`，`/api` 自动代理至 `127.0.0.1:8080`）。Demo 运行期数据默认保存在 `web-demo/backend/data/`。

## 算法验证

独立测试可灵图生图/图生视频提示词预设或运行本地 ComfyUI 工作流时，从仓库根目录执行以下命令（默认端口 `8000`，可用 `PET_PORT` 覆盖）。首次安装、网页 API 与 ComfyUI 使用方式见[算法验证说明](algorithm-lab/README.md)。

```bash
bash scripts/run.sh
bash scripts/test.sh
```

本机算法配置与任务历史分别位于 `algorithm-lab/.env` 和 `algorithm-lab/data/jobs/`，实验输入、输出与工作流均归入 `algorithm-lab/`，Python 虚拟环境共用仓库根的 `.venv/`。
