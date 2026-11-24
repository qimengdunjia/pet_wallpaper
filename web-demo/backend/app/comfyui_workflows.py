"""文件用途：将算法区已部署的 MiniMax H3 生图和 Pika H3 工作流组装为 ComfyUI API 执行图。"""

from __future__ import annotations

CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
FPS = 24
OUTPUT_NODE = "save"


def _node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def image_workflow(reference: str, prompt: str, size: tuple[int, int], seed: int, prefix: str) -> dict:
    """以服务器参考图、提示词、尺寸、种子和输出前缀，返回待机图生成图。"""
    width, height = size
    return {
        "reference": _node("LoadImage", image=reference),
        "model": _node("UNETLoader", unet_name="minimax_h3_image_pruned_int8_convrot.safetensors", weight_dtype="default"),
        "clip": _node("CLIPLoader", clip_name=CLIP, type="minimax", device="default"),
        "vae": _node("VAELoader", vae_name="minimax_h3_image_vae_fp16.safetensors"),
        "conditioning": _node("MiniMaxH3ImageConditioning", clip=["clip", 0], vae=["vae", 0],
                              prompt=f"<Picture 1> 为宠物参考图。{prompt}", width=width, height=height,
                              **{"images.image_1": ["reference", 0]}),
        "negative": _node("ConditioningZeroOut", conditioning=["conditioning", 0]),
        "sample": _node("KSampler", model=["model", 0], positive=["conditioning", 0], negative=["negative", 0],
                        latent_image=["conditioning", 1], seed=seed, steps=6, cfg=1, sampler_name="euler",
                        scheduler="simple", denoise=1),
        "decode": _node("VAEDecode", samples=["sample", 0], vae=["vae", 0]),
        OUTPUT_NODE: _node("SaveImage", images=["decode", 0], filename_prefix=prefix),
    }


def video_workflow(reference: str, prompt: str, size: tuple[int, int], seed: int, prefix: str) -> dict:
    """返回由模型生成全部画面帧的 4 秒视频执行图。

    参数：
        reference: 待机参考图在 ComfyUI 中的路径，用于首尾姿态条件。
        prompt: 该段视频的动作与画面描述。
        size: 成片的宽度和高度，单位为像素。
        seed: 模型采样的随机种子。
        prefix: ComfyUI 成片的文件名前缀。
    """
    width, height = size
    frames = 4 * FPS
    model_frames = frames + (5 - frames % 17) % 17  # H3 的合法帧数为 17k+5。
    timeline = (
        "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
        f"0.00-second mark; Picture 2 (from Shot 1) aligns with the {(model_frames - 1) / FPS:.2f}-second mark.\n\n"
        f"integrated_multimodal_description: [Shot 1] {prompt}\n\n"
        "overall_soundscape: None.\nnon_diegetic_music: None."
    )
    scale = {"width": width, "height": height, "upscale_method": "bicubic", "crop": "center"}
    return {
        "reference": _node("LoadImage", image=reference),
        "model": _node("UNETLoader", unet_name="minimax_h3_fl2va_pruned_fp8_scaled.safetensors", weight_dtype="default"),
        "lora": _node("LoraLoaderModelOnly", model=["model", 0], lora_name="pika_h3_flex_fl2va_v1_bf16.safetensors",
                      strength_model=1),
        "clip": _node("CLIPLoader", clip_name=CLIP, type="minimax", device="default"),
        "vae": _node("VAELoader", vae_name="minimax_h3_video_vae_fp16.safetensors"),
        # 复用算法区 1024×576 采样参数，随后独立调整成片尺寸。
        "conditioning": _node("MiniMaxH3ImageToVideo", clip=["clip", 0], vae=["vae", 0], prompt=timeline,
                              width=1024, height=576, length=model_frames, first_frame=["reference", 0],
                              last_frame=["reference", 0]),
        "noise": _node("RandomNoise", noise_seed=seed),
        "guider": _node("BasicGuider", model=["lora", 0], conditioning=["conditioning", 0]),
        "sampler": _node("KSamplerSelect", sampler_name="lcm"),
        "sigmas": _node("ManualSigmas", sigmas="1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"),
        "sample": _node("SamplerCustomAdvanced", noise=["noise", 0], guider=["guider", 0], sampler=["sampler", 0],
                        sigmas=["sigmas", 0], latent_image=["conditioning", 1]),
        "decode": _node("VAEDecode", samples=["sample", 0], vae=["vae", 0]),
        "preview": _node("CreateVideo", images=["decode", 0], fps=FPS),
        "resample": _node("VideoFrameSample", video=["preview", 0], num_frames=frames, strategy="uniform", seed=0),
        "components": _node("GetVideoComponents", video=["resample", 0]),
        # 首尾与中间帧统一使用模型解码结果，避免静态参考图带来的清晰度突变。
        "scale_frames": _node("ImageScale", image=["components", 0], **scale),
        "video": _node("CreateVideo", images=["scale_frames", 0], fps=FPS),
        OUTPUT_NODE: _node("SaveVideo", video=["video", 0], filename_prefix=prefix, format="mp4", **{"format.codec": "h264"}),
    }
