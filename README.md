<!-- 文件用途：提供宠物壁纸网页 Demo 与算法验证的仓库入口。 -->

# 宠物交互壁纸

项目面向横屏浏览器，计划通过网页演示猫狗录入、生成过场、三热区互动和多宠切换。网页 Demo 已完成目录与架构规划，算法验证工具可独立运行。

| 目录 | 用途 |
| --- | --- |
| [`web-demo/frontend/`](web-demo/frontend/README.md) | 网页交互与视频播放 |
| [`web-demo/backend/`](web-demo/backend/README.md) | 宠物档案、生成任务和素材交付 |
| [`web-demo/assets/`](web-demo/assets/README.md) | 公共过场和验收样例 |
| [`algorithm-lab/`](algorithm-lab/README.md) | 可灵网页验证、ComfyUI 工作流、素材实验和离线回归 |
| [`docs/`](docs/网页Demo开发文档.md) | 产品需求、网页架构和验收 |
| `scripts/` | 从仓库根启动与测试算法验证工具 |

开发入口见[网页 Demo 开发文档](docs/网页Demo开发文档.md)。行为与素材规格以 [PRD](docs/宠物交互壁纸_PRD.md) 为准，页面流程与设计参考[原型图](原型图.jpg)和 [MasterGo「页面 1」](https://mastergo.com/prototyping/210826940496035?fileOpenFrom=project&page_id=M)。

## 算法验证

已配置本机 Python 环境时，从仓库根执行以下命令。首次安装、网页 API 和 ComfyUI 使用方式见[算法验证说明](algorithm-lab/README.md)。

```bash
bash scripts/run.sh
bash scripts/test.sh
```

本机算法配置与任务历史分别位于 `algorithm-lab/.env` 和 `algorithm-lab/data/jobs/`。本机实验输入、输出和运行文件也归入 `algorithm-lab/`。Python 虚拟环境继续使用仓库根的 `.venv/`。
