<!-- 文件用途：记录 MiniMax H3 Image 的服务器部署、独立首尾帧工作流和验证结果。 -->

# MiniMax H3 Image

服务器：`z890ud`（CHERY-COM-30868）。部署目录：`/home/z890ud/workspace/tz/pet_wallpaper`。

ComfyUI 使用 v0.45.0，前端使用 1.58.5，通过原有 `pika-h3-flex.service` 同时提供网页与 API。
服务使用第一张 RTX 5090，监听 `127.0.0.1:8188`。
已有 SSH 隧道可继续通过 [本机 ComfyUI](http://127.0.0.1:18188/) 访问。

## 生成视频首尾帧

1. 在工作流列表打开 `image_minimax_h3_keyframes.json`，填写提示词并运行。
2. 默认输出 3072 × 1728 图片，6 步、CFG 1，种子为 42。图片保存至服务器 `.runtime/ComfyUI/output/minimax_h3_image/`。
3. 选择满意的图片，载入原视频工作流的 First frame / Last frame 节点。

生图和视频分支独立运行，图片不会自动替换视频输入。可选的 `image_1` 接口可连接参考图片进行编辑。
生图模型、文本编码器和图像 VAE 固定在生图子图内部；外层仅保留提示词、宽高、种子和参考图，避免模型下拉框缺少候选项或误用视频模型。

原 `video_pika_h3_flex_fl2va.json` 画布左侧也添加了相同的生图子图。
合并画布默认启用“保存首尾帧”、停用 SaveVideo，直接点击运行即可生图。
切换生成视频时，停用“保存首尾帧”并启用 SaveVideo。
至少保留一个保存节点启用；同时停用两个输出节点会提示“工作流未包含任何输出节点”。
节点启用状态可通过右键菜单修改，也可以选中节点后按 `Ctrl+M` 切换。
节点工具栏的蓝色运行按钮会执行到选中的输出节点，该输出节点必须处于启用状态。

本机副本：

- [独立生图工作流](../workflows/image_minimax_h3_keyframes.json)
- [包含独立生图分支的视频工作流](../workflows/video_pika_h3_flex_fl2va.json)

服务器工作流均位于 `.runtime/ComfyUI/user/default/workflows/`。
页面刷新后，重新从工作流列表打开文件即可载入更新。

## 权重与版本

使用 [Comfy-Org 官方模型仓库](https://huggingface.co/Comfy-Org/MiniMax-H3-Image)，固定版本
`0bb149f51e3156ed4b90dd45d5620346bfe1df8f`。

| 文件 | 大小 | 用途 |
| --- | ---: | --- |
| `diffusion_models/minimax_h3_image_pruned_int8_convrot.safetensors` | 20,979,314,802 字节 | 图像扩散模型 |
| `vae/minimax_h3_image_vae_fp16.safetensors` | 1,168,505,312 字节 | 图像 VAE |
| `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 15,687,142,551 字节 | 复用原视频工作流的文本编码器 |

新增两份权重通过 [下载脚本](../scripts/download_minimax_h3_image.py) 校验大小与 SHA-256。
生图子图从 [Comfy-Org 官方模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_minimax_h3_image_t2i.json)
提取基础生成链路，省去独立提示词扩写模型。

首次部署时的 570.195.03 驱动、PyTorch 2.11.0+cu128 无法运行模型默认的 CUDA 13 INT8 注意力内核，当时曾通过原生 `ModelAttentionBackend` 节点选择 `pytorch attention` 兼容运行。服务器环境随后另有升级，当前运行环境以服务器 README 和实际服务为准；本次输出修复保留当前生图子图的注意力实现。

## 服务管理与备份

在服务器项目目录执行：

```bash
systemctl --user start pika-h3-flex.service
systemctl --user status pika-h3-flex.service
journalctl --user -u pika-h3-flex.service -f
```

部署前工作流、启动脚本、README、服务配置、依赖列表和 ComfyUI 提交号保存在：
`.runtime/backups/minimax-h3-image-20261117/`。

## 验证

- 两份工作流已通过前端子图加载和执行图转换检查。
- 全局节点编号、连线编号、分组编号、端口和连线结构检查通过。
- 原视频连线、提示词、尺寸、种子和视频子图与部署前备份一致；合并画布的 SaveVideo 默认停用，供独立生图使用。
- 新增主模型与图像 VAE 的大小和 SHA-256 校验通过，依赖检查通过。
- 实际生图任务 `c5f2cad8-bd16-4a93-8f52-057376124548` 成功，输出 `minimax_h3_image/keyframe_00001_.png`（3072 × 1728）。此次执行用时 13.10 秒，复用了前一次尝试已缓存的文本条件及模型加载状态，不能作为冷启动耗时。
- 图片已目视检查；本机副本位于 `outputs/minimax_h3_image/keyframe_00001_.png`。
- 原视频 CLI 的小尺寸兼容性检查成功：任务 `4675a79f-0588-414c-b427-25ef646caa12` 输出 448 × 256、22 帧、24 fps 的 MP4。该检查只验证升级后的原视频链路可执行，不评价视频质量。
- 修复合并画布的默认输出状态后，直接点击 Pika 主画布的“运行”验证成功：任务 `c4b5814c-6048-49d9-821f-e9d0f4f34cde` 输出 `minimax_h3_image/keyframe_00002_.png`（3072 × 1728），未提交视频生成输出。此次修改保留了用户当前的节点布局和生成参数。
- 固定子图内部模型、保留用户参考图连线后，点击“保存首尾帧”节点工具栏中蓝色的“执行到选定的输出节点”按钮验证成功：任务 `eb682dbc-ff7c-46a7-b9e8-5c8ff2aab07b` 输出 `minimax_h3_image/keyframe_00003_.png`（3072 × 1728），无执行错误。
