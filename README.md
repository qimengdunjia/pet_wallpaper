<!-- 文件用途：说明宠物壁纸本机测试页、素材保存方式和恢复规则。 -->

# 宠物壁纸本机 Demo

用一张宠物正面照生成待机图，再选中同一张待机图测试不同动作。需求与素材规格见 [车机宠物交互壁纸 PRD](docs/宠物交互壁纸_PRD.md)。两个页面独立提交任务，素材和历史保存在本机，生成调用可灵 API。

## 启动

需要 Python 3.10+。在项目根目录安装依赖并准备配置：

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
cp -n .env.example .env
bash scripts/run.sh
```

在 `.env` 中填写 `KLING_API_KEY` 后重启。默认使用北京节点 `https://api-beijing.klingai.com`，可通过 `KLING_BASE_URL` 设置账户所在区域。服务仅在本机回环地址运行，每次执行一个图片批次或一个视频任务。端口被占用时可设置 `PET_PORT=8001`。

## 测试流程

1. 打开 [图生图](http://127.0.0.1:8000/image-to-image)，选「猫咪待机图」或「狗狗待机图」，上传一张宠物正面照。可在提示词中替换背景描述。生成后点「用这张图生成视频」。
2. 在 [图生视频](http://127.0.0.1:8000/image-to-video) 依次切换该物种的左、中、右预设，复用同一张首帧，每个方向生成一段。默认 Kling 3.0、4 秒、720p 和首尾复用。想做首帧约束的对照时，可将帧模式设为「仅首帧」。
3. 测追逐过场时，在图生图页选对应的关键帧预设，按顺序添加猫照、狗照。生成第一张过场图后，可将它下载作为第 3 张场景参考图，复用机位和背景。图生视频页按下表选择首尾帧，可直接从素材列表选择已生成的版本。
4. 成片下方可检查实际规格，并查看开头、中段和结尾。读取规格需要 `ffprobe`（随 FFmpeg 安装）。帧率取实际文件的平均帧率，规格不符会列出差异。逐段目视确认动作方向、背景稳定和衔接。检查先导接等待时，分别打开两条记录，对照先导末尾和等待段开头。

| 过场视频 | 首帧 | 尾帧 |
| --- | --- | --- |
| 首次录入 · 先导（3 秒） | 追逐 · 入场起始帧 | 追逐 · 猫前狗后关键帧 |
| 首次录入 · 等待循环（7 秒） | 与先导尾帧使用同一版本 | 留空复用首帧 |
| 跨种切换 · 猫切狗（3 秒） | 切换 · 猫居中关键帧 | 切换 · 狗居中关键帧 |
| 跨种切换 · 狗切猫（3 秒） | 切换 · 狗居中关键帧 | 切换 · 猫居中关键帧 |

图生图的「自定义 · 批量出图」继续支持多只主体独立生成，也可共用一张姿态风格底图。使用底图时选择 Image 3.0 Omni 或 Image O1，底图为参考图 1，主体为参考图 2。图生视频支持本机首尾帧上传及自定义提示词。选择 Kling 3.0 Omni 可上传至多 5 张额外参考图，按页面编号引用。

上传图片每张最多 10 MB，宽高至少 300 px。每次提交使用可灵账户额度。两页可分别切换本机历史，预览、下载或按原设置重做。生成中刷新页面可继续查看进度。

图生视频页可点素材库中的「添加图片」保存本机 JPG 或 PNG，之后可用作首帧或尾帧。每张素材都可单独删除。已生成的素材按版本移出，原图仍可从图生图历史查看和下载，已生成的视频保留提交时的帧副本。

## 保存提示词

在图生图或图生视频页选中一个预设，修改提示词后点「保存修改」。再次选中该预设会使用保存过的文字。点「另存为预设」可命名一个副本，在「生成预设」下的「自存提示词」中选用。编辑自定义提示词时可直接点「保存为预设」。两页的提示词预设分别保存在本机数据目录，重启后可继续使用。

## 保存和恢复

- `data/jobs/images/<任务 ID>/` 保存主体图 `original.jpg`、可选姿态风格底图 `style.jpg`、各版待机图 `idle-v1.jpg/png` 及 `job.json`。
- `data/jobs/videos/<任务 ID>/` 保存本次使用的首帧 `first.jpg/png`、可选尾帧 `tail.jpg`、各版成品 `video-v1.mp4` 等以及 `job.json`。
- 从素材区选择的首、尾帧会原样复制进视频任务，并记录来源任务和版本。源图片重做后，已有视频仍关联原先的版本。

重试查询或下载失败的任务会复用已记录的可灵任务 ID。若付费提交结果不明，页面会要求先在可灵控制台核对，再绑定任务 ID 或确认未创建。

## 接口

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/config` | 本机服务状态、默认提示词和视频模型参数 |
| `POST /api/image-batches` | 上传 1～10 个主体 `file`，每张建立独立任务，可共用一张 `style` 姿态风格图和同一组 `prompt`、`image_options` |
| `GET /api/image-batches/{id}` | 按上传顺序查看同批任务的进度和成品 |
| `POST /api/image-jobs` | 建立单个生成任务，可选 `preset`、`prompt` 和 `image_options`。普通 3.0 收一张原图，Omni 和 O1 可收有序参考图 |
| `GET /api/idle-images` | 素材库中的上传图片及生成图版本 |
| `POST /api/idle-images` | 上传 `file` 并加入素材库 |
| `DELETE /api/idle-images/uploads/{asset_id}` | 删除上传素材 |
| `DELETE /api/idle-images/{job_id}/{version}` | 从素材库移出指定的生成图版本 |
| `POST /api/video-jobs` | 首帧传 `file`、`source_asset_id` 或 `source_job_id` 与 `source_version`，另选 `preset` 或传 `prompt`。尾帧用 `tail` 或对应的 `tail_source_*` 字段 |
| `GET /api/jobs?kind=image` 或 `?kind=video` | 对应类型最近 50 条记录 |
| `GET /api/jobs/{id}` | 任务详情、生成状态和媒体地址 |
| `POST /api/jobs/{id}/retry` | 传入 `stage` 为 `idle` 或 `video`，恢复或重做任务 |
| `POST /api/jobs/{id}/reconcile` | 传入 `stage` 及 `provider_id` 或 `confirmed_not_created`，核对不明提交 |
| `GET /api/jobs/{id}/files/{name}` | 预览登记文件，`?download=true` 可下载 |
| `GET /api/jobs/{id}/video-info/{name}` | 读取已登记 MP4 的实际分辨率、画幅、帧率和时长 |

## 离线验证

```bash
.venv/bin/python3 -m pip install -r requirements-dev.txt
bash scripts/test.sh
```

回归使用模拟供应商，覆盖单步出图、历史待机图复用、首帧副本、视频参数与任务恢复。不会消耗真实生成额度。
