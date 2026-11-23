"""文件用途：提供网页、素材库、照片上传、任务操作和白名单成品访问的 FastAPI 服务。"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, ValidationError, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import prompts
from .config import ROOT, Settings
from .image import DEFAULT_IMAGE_OPTIONS, IMAGE_ASPECT_RATIOS, IMAGE_MODELS, MAX_IMAGE_REFERENCES, STANDARD_IMAGE_MODEL, ImageOptions
from .kling import KlingProvider, ProviderError
from .media import MediaProbeError, inspect_video
from .service import IMAGE_BATCH_CONCURRENCY, JobConflict, JobService
from .storage import FrameSource, normalize_photo
from .video import DEFAULT_VIDEO_OPTIONS, MIN_VIDEO_DURATION, VIDEO_MODELS, MAX_VIDEO_REFERENCES, OMNI_VIDEO_MODEL, VideoOptions
from .wallpaper import IMAGE_PRESETS, VIDEO_PRESETS, VIDEO_PRESET_LOOKUP

Stage = Literal["idle", "video"]
JobKind = Literal["image", "video"]
PromptText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2500)]
BUILTIN_PRESETS = {"image": IMAGE_PRESETS, "video": VIDEO_PRESET_LOOKUP}


class UpdatePromptPreset(BaseModel):
    """保存选中预设的提示词。参数 prompt 为用户编辑后的文本。"""

    prompt: PromptText


class SavePromptPreset(UpdatePromptPreset):
    """保存新预设。参数为提示词、显示名称以及可选的内置预设 ID。"""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    base_preset: str | None = None  # 另存时沿用原预设的生成规格与素材要求。


class RetryRequest(BaseModel):
    """单步操作请求；stage 为需要恢复或重做的阶段。"""

    stage: Stage


class ReconcileRequest(RetryRequest):
    """待核对操作；必须绑定远端 ID，或明确确认控制台没有创建任务。"""

    provider_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    confirmed_not_created: bool = False  # 只有用户核对控制台后才能置为真。

    @model_validator(mode="after")
    def validate_choice(self):
        """校验核对选项互斥；无额外参数，返回已验证的请求实例。"""
        if bool(self.provider_id) == self.confirmed_not_created:
            raise ValueError("请提供任务 ID，或明确确认未创建任务，二者只能选择一个")
        return self


def parse_video_options(raw: str | None, default: VideoOptions = DEFAULT_VIDEO_OPTIONS) -> VideoOptions:
    """解析可选视频设置 JSON；参数为空时返回指定默认值，非法设置返回 HTTP 422。"""
    try:
        return default if raw is None else VideoOptions.model_validate_json(raw)
    except ValidationError as exc:
        error = exc.errors(include_input=False)[0]
        detail = str(error["ctx"]["error"]) if error["type"] == "value_error" else "视频参数无效，请检查模型、时长、分辨率和帧模式"
        raise HTTPException(422, detail) from exc


def parse_image_options(raw: str | None) -> ImageOptions:
    """解析可选图片设置 JSON；参数为空时返回默认值，无效时返回 HTTP 422。"""
    try:
        return DEFAULT_IMAGE_OPTIONS if raw is None else ImageOptions.model_validate_json(raw)
    except ValidationError as exc:
        error = exc.errors(include_input=False)[0]
        detail = str(error["ctx"]["error"]) if error["type"] == "value_error" else "图片参数无效，请检查模型、分辨率和画幅"
        raise HTTPException(422, detail) from exc


async def read_photo(file: UploadFile, limit: int) -> bytes:
    """读取并校验一张上传图片；参数为文件和字节上限，返回规范化后的 JPEG。"""
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"图片不能超过 {limit // 1024 // 1024} MB")
    try:
        return await asyncio.to_thread(normalize_photo, content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def parse_frame_source(asset_id: str | None, job_id: str | None, version: int | None) -> FrameSource | None:
    """校验互斥的素材来源；参数为上传素材 ID 或生成任务 ID 与版本，返回来源标识。"""
    if (job_id is None) != (version is None) or (asset_id is not None and job_id is not None):
        raise HTTPException(422, "每帧只能指定一个素材，生成图需同时提供任务和版本")
    if asset_id is not None:
        return asset_id, None
    if job_id is not None:
        return job_id, version
    return None


def create_app(settings: Settings | None = None, provider=None) -> FastAPI:
    """构造服务；参数为可选配置和供应商测试替身，返回独立 FastAPI 应用。"""
    config = settings or Settings.from_env()
    service = JobService(config, provider or KlingProvider(config))

    @asynccontextmanager
    async def lifespan(application):
        await service.start()
        try:
            yield
        finally:
            await service.close()

    application = FastAPI(title="宠物壁纸本机 Demo", lifespan=lifespan)
    application.state.service = service
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @application.middleware("http")
    async def local_guard(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "仅允许本机网页同源操作"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "不允许跨站请求"}, status_code=403)
            length = request.headers.get("content-length")
            path = request.url.path.rstrip("/")
            image_count = {
                "/api/image-jobs": MAX_IMAGE_REFERENCES,
                "/api/image-batches": MAX_IMAGE_REFERENCES + 1,
                "/api/video-jobs": 2 + MAX_VIDEO_REFERENCES,
            }.get(path, 1)
            if length and (not length.isdigit() or int(length) > image_count * config.max_upload + 1024 * 1024):
                return JSONResponse({"detail": "上传文件过大"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; media-src 'self'; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @application.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({"detail": "任务或文件不存在"}, status_code=404)

    @application.exception_handler(JobConflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @application.exception_handler(ProviderError)
    async def unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @application.get("/")
    @application.get("/image-to-image")
    async def index():
        """打开图生图测试页；无参数，返回本地 HTML。"""
        return FileResponse(ROOT / "web" / "index.html")

    @application.get("/image-to-video")
    async def video_playground():
        """打开独立图生视频测试页；无参数，返回本地 HTML。"""
        return FileResponse(ROOT / "web" / "image-to-video.html")

    @application.get("/api/config")
    async def configuration():
        """读取网页配置；无参数，返回服务状态与可用的图像和视频参数。"""
        return {"configured": bool(config.api_key), "busy": service.busy,
                "active_job_id": service.active_id if service.busy else None,
                "max_upload_mb": config.max_upload // 1024 // 1024,
                "default_image_prompt": prompts.IDLE_SINGLE,
                "default_image_style_prompt": prompts.IDLE_WITH_STYLE,
                "max_image_references": MAX_IMAGE_REFERENCES,
                "image_batch_concurrency": IMAGE_BATCH_CONCURRENCY,
                "image_models": IMAGE_MODELS, "image_aspect_ratios": IMAGE_ASPECT_RATIOS,
                "default_image_options": DEFAULT_IMAGE_OPTIONS.model_dump(),
                "video_models": VIDEO_MODELS, "min_video_duration": MIN_VIDEO_DURATION,
                "default_video_options": DEFAULT_VIDEO_OPTIONS.model_dump(),
                "image_presets": IMAGE_PRESETS, "video_presets": VIDEO_PRESETS}

    @application.get("/api/jobs")
    async def list_jobs(kind: JobKind = "image"):
        """列出本机历史任务；参数为任务类型，返回该类型最近 50 条公开状态。"""
        jobs = [job for job in service.store.all() if job["kind"] == kind]
        return {"jobs": [service.store.public(job) for job in jobs[:50]]}

    @application.get("/api/prompt-presets/{kind}")
    async def list_prompt_presets(kind: JobKind):
        """按测试页读取持久化提示词。参数为测试类型，返回自存预设与内置预设的修改。"""
        return {"presets": service.store.prompt_presets(kind)}

    @application.post("/api/prompt-presets/{kind}", status_code=201)
    async def create_prompt_preset(kind: JobKind, body: SavePromptPreset):
        """将提示词另存为预设。参数为测试类型和新预设内容，返回已保存的记录。"""
        if body.base_preset is not None and body.base_preset not in BUILTIN_PRESETS[kind]:
            raise HTTPException(422, "找不到对应的生成预设")
        presets = service.store.prompt_presets(kind)
        if any(item.get("name", "").casefold() == body.name.casefold() for item in presets.values()):
            raise HTTPException(409, "已有同名预设，请使用其他名称")
        preset_id = f"custom-{uuid.uuid4().hex}"
        record = body.model_dump()
        presets[preset_id] = record
        service.store.save_prompt_presets(kind, presets)
        return {"id": preset_id, **record}

    @application.put("/api/prompt-presets/{kind}/{preset_id}")
    async def update_prompt_preset(kind: JobKind, preset_id: str, body: UpdatePromptPreset):
        """更新某个预设的提示词。参数为测试类型、预设 ID 和新文本，返回已保存的记录。"""
        presets = service.store.prompt_presets(kind)
        if preset_id not in BUILTIN_PRESETS[kind] and preset_id not in presets:
            raise HTTPException(404, "找不到要修改的预设")
        record = {**presets.get(preset_id, {}), "prompt": body.prompt}
        presets[preset_id] = record
        service.store.save_prompt_presets(kind, presets)
        return {"id": preset_id, **record}

    @application.post("/api/video-jobs", status_code=202)
    async def create_video_job(prompt: str | None = Form(None), file: UploadFile | None = File(None),
                               tail: UploadFile | None = File(None), reference: list[UploadFile] | None = File(None),
                               video_options: str | None = Form(None),
                               source_job_id: str | None = Form(None),
                               source_version: int | None = Form(None, ge=1),
                               source_asset_id: str | None = Form(None),
                               tail_source_job_id: str | None = Form(None),
                               tail_source_version: int | None = Form(None, ge=1),
                               tail_source_asset_id: str | None = Form(None),
                               preset: str | None = Form(None)):
        """从上传文件或素材库生成视频；参数含提示词、选项和可选尾帧，返回任务摘要。"""
        try:
            service.ensure_available()
            spec = VIDEO_PRESET_LOOKUP.get(preset) if preset is not None else None
            if preset is not None and spec is None:
                raise HTTPException(422, "未知的视频预设")
            if prompt is None and spec:
                prompt = service.store.prompt_presets("video").get(preset, spec)["prompt"]
            prompt = (prompt or "").strip()
            if not 1 <= len(prompt) <= 2500:
                raise HTTPException(422, "提示词需为 1～2500 个字符")
            source = parse_frame_source(source_asset_id, source_job_id, source_version)
            if (file is None) == (source is None):
                raise HTTPException(422, "请上传首帧或从素材库选择一张图片")
            tail_source = parse_frame_source(tail_source_asset_id, tail_source_job_id, tail_source_version)
            if tail and tail_source:
                raise HTTPException(422, "尾帧请从素材库选择一张图片或上传一个文件")
            defaults = VideoOptions.model_validate(spec["options"]) if spec else VideoOptions(
                frame_mode="first_last" if tail or tail_source else "first"
            )
            options = parse_video_options(video_options, defaults)
            if (tail or tail_source) and options.frame_mode != "first_last":
                raise HTTPException(422, "指定尾帧时请选择首尾帧模式")
            if spec and spec["tail_hint"] and options.frame_mode == "first_last" and not (tail or tail_source):
                raise HTTPException(422, "该预设的首尾帧模式需要指定尾帧")
            if reference and options.model != OMNI_VIDEO_MODEL:
                raise HTTPException(422, "额外参考图仅支持 Kling 3.0 Omni")
            if reference and len(reference) > MAX_VIDEO_REFERENCES:
                raise HTTPException(422, f"最多添加 {MAX_VIDEO_REFERENCES} 张额外参考图")
            reference_photos = [await read_photo(item, config.max_upload) for item in (reference or [])]
            first_photo = await read_photo(file, config.max_upload) if file else None
            tail_photo = await read_photo(tail, config.max_upload) if tail else None
            job = await service.create(first_photo, options, video_prompt=prompt, tail_photo=tail_photo, idle_source=source,
                                       video_references=reference_photos, tail_source=tail_source, preset=preset)
            return service.store.public(job)
        finally:
            if file:
                await file.close()
            if tail:
                await tail.close()
            for item in reference or []:
                await item.close()

    async def read_image_submission(file: list[UploadFile], prompt: str | None, image_options: str | None,
                                    style: list[UploadFile] | None = None):
        try:
            service.ensure_available()
            if not 1 <= len(file) <= MAX_IMAGE_REFERENCES:
                raise HTTPException(422, f"请选择 1～{MAX_IMAGE_REFERENCES} 张图片")
            if style and len(style) > 1:
                raise HTTPException(422, "一批只能选择一张姿态风格参考图")
            default_prompt = prompts.IDLE_WITH_STYLE if style else prompts.IDLE_SINGLE
            prompt = default_prompt if prompt is None else prompt.strip()
            if not 1 <= len(prompt) <= 2500:
                raise HTTPException(422, "提示词需为 1～2500 个字符")
            options = parse_image_options(image_options)
            if style and options.model == STANDARD_IMAGE_MODEL:
                raise HTTPException(422, "使用姿态风格参考图时，请选择 Image 3.0 Omni 或 Image O1")
            photos = [await read_photo(upload, config.max_upload) for upload in file]
            style_photo = await read_photo(style[0], config.max_upload) if style else None
            return photos, prompt, options, style_photo
        finally:
            for upload in [*file, *(style or [])]:
                await upload.close()

    @application.post("/api/image-jobs", status_code=202)
    async def create_image_job(file: list[UploadFile] = File(...), prompt: str | None = Form(None),
                               image_options: str | None = Form(None), preset: str | None = Form(None)):
        """用有序的参考图生成单张待机图；参数为图片列表、提示词和设置，返回任务摘要。"""
        spec = IMAGE_PRESETS.get(preset) if preset is not None else None
        if preset is not None and spec is None:
            raise HTTPException(422, "未知的图片预设")
        if spec and prompt is None:
            prompt = service.store.prompt_presets("image").get(preset, spec)["prompt"]
        photos, prompt, options, _ = await read_image_submission(file, prompt, image_options)
        if options.model == STANDARD_IMAGE_MODEL and len(photos) != 1:
            raise HTTPException(422, "普通 Image 3.0 单任务接收一张原图，多图独立生成请使用批次接口")
        if spec:
            if not spec["min_photos"] <= len(photos) <= spec["max_photos"]:
                raise HTTPException(422, "图片数量与所选预设不符")
            if options.aspect_ratio != "16:9":
                raise HTTPException(422, "车机图片预设使用 16:9 画幅")
        job = await service.create(photos[0], image_prompt=prompt, image_options=options,
                                   additional_photos=photos[1:], preset=preset)
        return service.store.public(job)

    @application.post("/api/image-batches", status_code=202)
    async def create_image_batch(file: list[UploadFile] = File(...), prompt: str | None = Form(None),
                                 image_options: str | None = Form(None), style: list[UploadFile] | None = File(None)):
        """每张主体图独立生成待机图；参数为主体图、可选共用姿态风格图、提示词和设置，返回批次任务。"""
        photos, prompt, options, style_photo = await read_image_submission(file, prompt, image_options, style)
        jobs = await service.create_image_batch(photos, prompt, options, style_photo=style_photo)
        return {"jobs": [service.store.public(job) for job in jobs]}

    @application.get("/api/image-batches/{batch_id}")
    async def get_image_batch(batch_id: str):
        """读取批次进度；参数为批次 ID，返回按原图顺序排列的任务。"""
        jobs = [job for job in service.store.all() if job.get("batch_id") == batch_id]
        if not jobs:
            raise FileNotFoundError("批次不存在")
        jobs.sort(key=lambda job: job["batch_index"])
        return {"jobs": [service.store.public(job) for job in jobs]}

    @application.get("/api/idle-images")
    async def list_idle_images():
        """读取素材库；无参数，返回可复用的上传素材和生成图版本。"""
        return {"images": service.store.idle_images()}

    @application.post("/api/idle-images", status_code=201)
    async def add_idle_image(file: UploadFile = File(...)):
        """把本机图片加入素材库；参数为上传文件，返回新素材记录。"""
        try:
            photo = await read_photo(file, config.max_upload)
            return service.store.add_idle_image(photo, file.filename or "")
        finally:
            await file.close()

    @application.get("/api/idle-images/uploads/{asset_id}")
    async def get_uploaded_image(asset_id: str):
        """预览已登记的上传素材；参数为素材 ID，返回图片内容。"""
        photo = service.store.uploaded_image(asset_id).read_bytes()
        return Response(photo, media_type="image/jpeg")

    @application.delete("/api/idle-images/uploads/{asset_id}")
    async def delete_uploaded_image(asset_id: str):
        """删除上传素材；参数为素材 ID，返回删除结果。"""
        service.store.remove_idle_image((asset_id, None))
        return {"deleted": True}

    @application.delete("/api/idle-images/{job_id}/{version}")
    async def delete_generated_image(job_id: str, version: int):
        """从素材库移出生成图；参数为任务 ID 与版本，返回删除结果。"""
        service.store.remove_idle_image((job_id, version))
        return {"deleted": True}

    @application.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        """获取任务状态；参数为任务 ID，返回阶段、版本、错误和成品本地地址。"""
        return service.store.public(service.store.load(job_id))

    @application.post("/api/jobs/{job_id}/retry", status_code=202)
    async def retry_job(job_id: str, body: RetryRequest):
        """恢复失败步骤或单步重做；参数为任务 ID 与阶段，返回最新任务摘要。"""
        return service.store.public(await service.retry(job_id, body.stage))

    @application.post("/api/jobs/{job_id}/reconcile", status_code=202)
    async def reconcile_job(job_id: str, body: ReconcileRequest):
        """核对不明提交后继续；参数为阶段与核对结果，返回当前任务摘要。"""
        return service.store.public(await service.reconcile(job_id, body.stage, body.provider_id, body.confirmed_not_created))

    @application.get("/api/jobs/{job_id}/files/{name}")
    async def get_file(job_id: str, name: str, download: bool = False):
        """访问登记文件；参数为任务 ID、文件名和下载标记，返回支持 Range 的文件响应。"""
        path = service.store.file(service.store.load(job_id), name)
        return FileResponse(path, filename=path.name if download else None)

    @application.get("/api/jobs/{job_id}/video-info/{name}")
    def video_info(job_id: str, name: str):
        """读取成片实际规格。参数为任务 ID 与已登记的视频文件名，返回探测结果。"""
        job = service.store.load(job_id)
        if job["kind"] != "video" or not name.endswith(".mp4"):
            raise FileNotFoundError("视频不存在")
        path = service.store.file(job, name)
        try:
            return inspect_video(path)
        except MediaProbeError as exc:
            raise HTTPException(503, str(exc)) from exc

    application.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")
    return application


app = create_app()
