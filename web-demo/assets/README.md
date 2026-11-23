<!-- 文件用途：说明网页 Demo 的公共过场与示例素材目录及生成脚本。 -->

# 公共过场、默认壁纸与演示素材

本目录归档符合 1920×1080、16:9、24 fps、H.264 规格的公共过场、默认狗狗动态壁纸与模拟生成样例，统一由 [`manifest.json`](manifest.json) 索引。

| 路径 | 用途 | 规格 |
| --- | --- | --- |
| `transitions/intro-3s.mp4` | 首次录入/生成等待入场先导（只播一次，末尾接追逐首帧） | 1920×1080 · 24 fps · 3.0s |
| `transitions/chase-loop-7s.mp4` | 追逐等待循环（猫狗循环追逐动画） | 1920×1080 · 24 fps · 7.0s |
| `default-wallpaper/` | 预置默认狗狗壁纸（静态首帧 `idle.jpg`、动态待机 `idle.mp4` 及左/中/右三热区视频） | 1920×1080 · 24 fps · ~4.46s |
| `samples/cat/` | 猫咪待机图 `idle.jpg`、示例上传照 `sample-upload.jpg` 及左/中/右三热区视频 | 1920×1080 · 24 fps · ~4.04s |
| `samples/dog/` | 狗狗待机图 `idle.jpg`、示例上传照 `sample-upload.jpg` 及左/中/右三热区视频 | 1920×1080 · 24 fps · ~4.04s |
| `prepare_assets.py` | 探测/规整资产视频并实测生成 `manifest.json`（加 `--rebuild-transitions` 可重建合成占位过场） | Python + FFmpeg |

重新生成或更新样例后，可在仓库根目录执行：

```bash
.venv/bin/python3 web-demo/assets/prepare_assets.py
```

详情与验收要求见 [PRD](../../docs/宠物交互壁纸_PRD.md) 与[网页 Demo 开发文档](../../docs/网页Demo开发文档.md)。
