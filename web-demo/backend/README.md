<!-- 文件用途：说明宠物壁纸网页 Demo 后端服务架构、接口与运行配置。 -->

# 网页 Demo 后端

本目录实现单应用同源部署的 Python FastAPI + SQLite 后端，负责宠物档案、照片校验存档、幂等异步生成、成品校验发布、上次成功壁纸恢复、Range 视频读取以及同源静态前端托管。

## 目录结构

- [`app/config.py`](app/config.py)：读取 `.env` 与环境变量中的供应商地址、数据目录和设置密码
- [`app/db.py`](app/db.py)：使用 SQLite WAL 持久化宠物档案、生成任务、生成设置以及壁纸版本
- [`app/media.py`](app/media.py)：照片规范化校验、FFprobe 视频规格读取、版本资产完整性校验
- [`app/providers.py`](app/providers.py)：`mock` 和 `kling` 生成适配器，可灵复用 `algorithm-lab` 的 PRD 提示词
- [`app/comfyui.py`](app/comfyui.py)：提交 MiniMax H3 生图和 Pika H3 视频任务，查询历史并下载成品
- [`app/worker.py`](app/worker.py)：单实例任务锁、并发生成调度与进程重启恢复
- [`app/main.py`](app/main.py)：API 路由、同源静态文件托管与 HTTP Range 支持
- [`tests/test_api.py`](tests/test_api.py)：接口、幂等、Range 请求、重启恢复与可灵适配器单测

## 配置与运行

在仓库根目录执行以下命令即可启动（默认使用 `mock` 模式，端口 `8080`）：

```bash
cp -n web-demo/backend/.env.example web-demo/backend/.env
bash scripts/run_demo.sh
```

点击 Demo 底栏的齿轮，输入密码进入「生成设置」。密码由 `DEMO_SETTINGS_PASSWORD` 指定，留空时服务首次启动会生成密码并写入数据目录的 `settings-password`。默认路径是 `web-demo/backend/data/settings-password`。

使用 ComfyUI 时，将 `z890ud` 的 `8188` 端口转发到本机 `18188`，并在设置页选择 ComfyUI。服务地址可由后端的 `COMFYUI_BASE_URL` 覆盖。默认生图尺寸为 2560×1440。视频以 1344×768 采样，首尾共用等比居中裁切至采样尺寸的参考图，成片默认等比居中裁切为 1920×1080、24 fps 的 MP4。待机、左侧、中央和右侧各有一段四秒视频，猫咪与狗狗分别保存提示词。

```bash
ssh -N -L 127.0.0.1:18188:127.0.0.1:8188 z890ud
```

双卡部署时，在 z890ud 上将两个 ComfyUI 实例分别绑定 GPU 0 和 GPU 1，仅监听本机的 `8188` 和 `8189`。两个实例共用模型、输入及输出目录，分别使用自己的用户目录、数据库和临时目录。后端配置 `COMFYUI_SECONDARY_BASE_URL=http://127.0.0.1:18189`，并转发第二个端口。待机图由主实例生成。四段视频进入同一队列，空闲实例每次领取一段，先完成的实例接着领取下一段。第二实例不可用时，尚未提交的视频由主实例生成。重启后，已提交的视频继续从原实例恢复。

```bash
ssh -N -L 127.0.0.1:18188:127.0.0.1:8188 -L 127.0.0.1:18189:127.0.0.1:8189 z890ud
```

可灵需在 `web-demo/backend/.env` 中配置 `KLING_API_KEY`。可灵使用待机图和三个交互提示词。待机视频提示词和可编辑分辨率用于 ComfyUI。设置页保存后立即作用于新任务，同时保存在 SQLite 中，重启后继续生效。`DEMO_PROVIDER` 用于首次保存之前的初始模式。
