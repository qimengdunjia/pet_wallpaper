<!-- 文件用途：说明宠物壁纸网页 Demo 后端服务架构、接口与运行配置。 -->

# 网页 Demo 后端

本目录实现单应用同源部署的 Python FastAPI + SQLite 后端，负责宠物档案、照片校验存档、幂等异步生成、成品校验发布、上次成功壁纸恢复、Range 视频读取以及同源静态前端托管。

## 目录结构

- [`app/config.py`](app/config.py)：读取 `.env` 与环境变量配置（供应商模式、数据目录、可灵配置）
- [`app/db.py`](app/db.py)：SQLite WAL 持久化（`pets`、`generation_jobs`、`asset_versions`、`current_wallpapers`）
- [`app/media.py`](app/media.py)：照片规范化校验、FFprobe 视频规格读取、版本资产完整性校验
- [`app/providers.py`](app/providers.py)：`mock` 和 `kling` 生成适配器，可灵复用 `algorithm-lab` 的 PRD 提示词
- [`app/worker.py`](app/worker.py)：单实例任务锁、并发生成调度与进程重启恢复
- [`app/main.py`](app/main.py)：API 路由、同源静态文件托管与 HTTP Range 支持
- [`tests/test_api.py`](tests/test_api.py)：接口、幂等、Range 请求、重启恢复与可灵适配器单测

## 配置与运行

在仓库根目录执行以下命令即可启动（默认使用 `mock` 模式，端口 `8080`）：

```bash
cp -n web-demo/backend/.env.example web-demo/backend/.env
bash scripts/run_demo.sh
```

在 `web-demo/backend/.env` 中配置 `DEMO_PROVIDER=kling` 和 `KLING_API_KEY` 可使用可灵真实生成。ComfyUI 工作流使用[算法验证区](../../algorithm-lab/README.md)运行。
