<!-- 文件用途：说明网页 Demo 的公共过场与示例素材目录及生成脚本。 -->

# 公共过场、默认壁纸与演示素材

本目录归档符合 1920×1080、16:9、24 fps、H.264 规格的公共过场、默认狗狗动态壁纸与模拟生成样例，统一由 [`manifest.json`](manifest.json) 索引。

两段公共过场采用分片 MP4，浏览器可将先导和后续循环追加到同一个视频元素。素材脚本会识别分片和编码类型，并生成播放所需的清单字段。

| 路径 | 用途 | 规格 |
| --- | --- | --- |
| `transitions/intro-3s.mp4` | 首次录入或生成等待时播放一次的入场先导，保留模型生成的所有导出帧 | 1920×1080 · 24 fps · 72 帧 · 3.000 秒 |
| `transitions/chase-loop-7s.mp4` | 猫狗追逐等待循环，从模型输出中保留第 2–165 帧和末帧第 167 帧，帧序号从 0 开始 | 1920×1080 · 24 fps · 165 帧 · 6.875 秒 |
| `default-wallpaper/` | 预置默认狗狗壁纸（静态首帧 `idle.jpg`、动态待机 `idle.mp4` 及左/中/右三热区视频） | 1920×1080 · 24 fps · ~4.46s |
| `samples/cat/` | 猫咪待机图 `idle.jpg`、示例上传照 `sample-upload.jpg` 及左/中/右三热区视频 | 1920×1080 · 24 fps · ~4.04s |
| `samples/dog/` | 狗狗待机图 `idle.jpg`、示例上传照 `sample-upload.jpg` 及左/中/右三热区视频 | 1920×1080 · 24 fps · ~4.04s |
| `prepare_assets.py` | 探测/规整资产视频并实测生成 `manifest.json`（加 `--rebuild-transitions` 可重建合成占位过场） | Python + FFmpeg |

重新生成或更新样例后，可在仓库根目录执行：

```bash
.venv/bin/python3 web-demo/assets/prepare_assets.py
```

详情与验收要求见 [PRD](../../docs/宠物交互壁纸_PRD.md) 与[网页 Demo 开发文档](../../docs/网页Demo开发文档.md)。
