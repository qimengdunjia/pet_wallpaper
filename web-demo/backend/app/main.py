"""文件用途：网页 Demo FastAPI 主应用，提供宠物档案、幂等生成、任务恢复、媒体范围读取与同源前端托管。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from .config import Settings
from .db import DemoDatabase, GenerationKeyConflict
from .media import PhotoValidationError, normalize_photo
from .providers import BaseGenerationProvider, build_provider
from .worker import GenerationWorker

SESSION_COOKIE = "pet_demo_session"
Species = Literal["cat", "dog"]
Gender = Literal["弟弟", "妹妹", "未设置"]
PetName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]


class CreatePetRequest(BaseModel):
    species: Species
    name: OptionalText = ""
    gender: Gender = "未设置"
    breed: OptionalText = ""


class UpdatePetRequest(BaseModel):
    name: PetName | None = None
    gender: Gender | None = None
    breed: OptionalText | None = None


class CurrentWallpaperRequest(BaseModel):
    pet_id: str = Field(min_length=1, max_length=64)
    version_id: str = Field(min_length=1, max_length=64)


def resolve_session_id(request: Request) -> str:
    """从请求头、查询参数或演示会话 Cookie 提取并清洗会话标识。"""
    raw = (
        request.headers.get("X-Demo-Session")
        or request.query_params.get("session")
        or request.cookies.get(SESSION_COOKIE)
        or "default"
    )
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", raw)[:64]
    return cleaned or "default"


def _session_suffix(session_id: str) -> str:
    return f"?session={session_id}" if session_id != "default" else ""


def _default_pet_name(species: Species, existing_pets: list[dict]) -> str:
    prefix = "猫咪" if species == "cat" else "狗狗"
    count = sum(1 for item in existing_pets if item["species"] == species) + 1
    return f"{prefix} {count}"


def serialize_version(version: dict, session_id: str = "default") -> dict:
    """将数据库素材版本转换为对外清单（含格式、分辨率、帧率和时长）。"""
    vid = version["id"]
    suffix = _session_suffix(session_id)
    actions = {}
    for slot in ("left", "center", "right"):
        meta = dict(version["actions"][slot])
        meta.pop("file_path", None)
        actions[slot] = {
            "url": f"/api/media/versions/{vid}/{slot}{suffix}",
            **meta,
        }
    return {
        "version_id": vid,
        "version_number": version["version_number"],
        "created_at": version["created_at"],
        "idle_image": {
            "url": f"/api/media/versions/{vid}/idle{suffix}",
            **version["idle_meta"],
        },
        "actions": actions,
    }


def serialize_job(job: dict, db: DemoDatabase, session_id: str = "default") -> dict:
    """转换生成任务公开结构，就绪时附该版本素材清单。"""
    assets = None
    if job["status"] == "ready" and job.get("version_id"):
        version = db.get_version(job["version_id"])
        if version:
            assets = serialize_version(version, session_id)
    return {
        "id": job["id"],
        "pet_id": job["pet_id"],
        "idempotency_key": job["idempotency_key"],
        "provider": job["provider"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "version_id": job["version_id"],
        "error_message": job["error_message"],
        "assets": assets,
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def serialize_pet(pet: dict, db: DemoDatabase, session_id: str = "default") -> dict:
    """转换宠物档案公开结构，附可用素材版本及最近一次生成任务。"""
    suffix = _session_suffix(session_id)
    active_assets = None
    if pet.get("active_version_id"):
        version = db.get_version(pet["active_version_id"])
        if version:
            active_assets = serialize_version(version, session_id)
    latest_job = None
    if pet.get("latest_job_id"):
        job = db.get_job_any(pet["latest_job_id"])
        if job:
            latest_job = serialize_job(job, db, session_id)
    return {
        "id": pet["id"],
        "species": pet["species"],
        "name": pet["name"],
        "gender": pet["gender"],
        "breed": pet["breed"],
        "original_photo_url": f"/api/media/pets/{pet['id']}/original{suffix}" if pet.get("original_photo_path") else None,
        "active_version_id": pet["active_version_id"],
        "latest_job_id": pet["latest_job_id"],
        "active_assets": active_assets,
        "latest_job": latest_job,
        "created_at": pet["created_at"],
        "updated_at": pet["updated_at"],
    }


def _load_assets_manifest(assets_dir: Path) -> dict:
    manifest_file = assets_dir / "manifest.json"
    if manifest_file.is_file():
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    return {"transitions": {}, "samples": {}}


def create_app(
    settings: Settings | None = None,
    provider: BaseGenerationProvider | None = None,
) -> FastAPI:
    """构造独立 FastAPI 实例；支持注入自定义配置与测试供应商。"""
    config = settings or Settings.from_env()
    db = DemoDatabase(config.data_dir / "demo.sqlite3")
    active_provider = provider or build_provider(config)
    worker = GenerationWorker(config, db, active_provider)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await worker.start()
        try:
            yield
        finally:
            await worker.close()
            db.close()

    app = FastAPI(title="宠物交互壁纸网页 Demo", lifespan=lifespan)
    app.state.settings = config
    app.state.db = db
    app.state.worker = worker

    @app.middleware("http")
    async def demo_security_and_session(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            host = request.headers.get("host")
            if origin and host and urlparse(origin).netloc != host:
                return JSONResponse({"detail": "仅允许同源操作"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "禁止跨站请求"}, status_code=403)

        response = await call_next(request)
        if (
            not request.cookies.get(SESSION_COOKIE)
            and not request.headers.get("X-Demo-Session")
            and not request.query_params.get("session")
        ):
            response.set_cookie(SESSION_COOKIE, "default", httponly=False, samesite="lax", path="/")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/media/") or request.url.path.startswith("/api/assets/"):
            response.headers.setdefault("Accept-Ranges", "bytes")
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.get("/api/config")
    def get_config():
        """返回后端运行模式、Mock 演示控制开关与过场视频清单。"""
        manifest = _load_assets_manifest(config.assets_dir)
        transitions = manifest.get("transitions", {})
        intro = transitions.get("intro", {})
        loop = transitions.get("loop", {})
        return {
            "provider": config.provider,
            "mock_controls_enabled": config.mock_controls_enabled,
            "default_mock_delay_seconds": config.mock_delay_seconds,
            "max_upload_mb": config.max_upload_bytes // 1024 // 1024,
            "transitions": {
                "intro": {**intro, "url": "/api/assets/transitions/intro-3s.mp4"} if intro else None,
                "loop": {**loop, "url": "/api/assets/transitions/chase-loop-7s.mp4"} if loop else None,
            },
            "sample_uploads": {
                "cat": "/api/assets/samples/cat/upload",
                "dog": "/api/assets/samples/dog/upload",
            },
        }

    @app.get("/api/assets/manifest")
    def get_assets_manifest():
        return _load_assets_manifest(config.assets_dir)

    @app.get("/api/assets/transitions/{filename}")
    def get_transition_asset(filename: str):
        allowed = {
            "intro-3s.mp4": config.assets_dir / "transitions" / "intro-3s.mp4",
            "chase-loop-7s.mp4": config.assets_dir / "transitions" / "chase-loop-7s.mp4",
        }
        target = allowed.get(filename)
        if not target or not target.is_file():
            raise HTTPException(404, "过场素材不存在")
        return FileResponse(target, media_type="video/mp4")

    @app.get("/api/assets/samples/{species}/upload")
    def get_sample_upload(species: Species):
        target = config.assets_dir / "samples" / species / "sample-upload.jpg"
        if not target.is_file():
            raise HTTPException(404, "示例照片不存在")
        return FileResponse(target, media_type="image/jpeg")

    @app.get("/api/pets")
    def list_pets(request: Request):
        session_id = resolve_session_id(request)
        pets = db.list_pets(session_id)
        return {"pets": [serialize_pet(pet, db, session_id) for pet in pets]}

    @app.post("/api/pets", status_code=201)
    def create_pet(request: Request, body: CreatePetRequest):
        session_id = resolve_session_id(request)
        existing = db.list_pets(session_id)
        name = body.name or _default_pet_name(body.species, existing)
        pet = db.create_pet(session_id, body.species, name, body.gender, body.breed)
        return {"pet": serialize_pet(pet, db, session_id)}

    @app.patch("/api/pets/{pet_id}")
    def update_pet(request: Request, pet_id: str, body: UpdatePetRequest):
        session_id = resolve_session_id(request)
        pet = db.update_pet(
            session_id,
            pet_id,
            name=body.name,
            gender=body.gender,
            breed=body.breed,
        )
        if not pet:
            raise HTTPException(404, "宠物档案不存在")
        return {"pet": serialize_pet(pet, db, session_id)}

    @app.post("/api/generations")
    async def submit_generation(
        request: Request,
        pet_id: str = Form(...),
        photo: UploadFile | None = File(None),
        idempotency_key: str | None = Form(None),
        idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
        mock_delay_seconds: float | None = Form(None),
        mock_fail: bool = Form(False),
        mock_fail_stage: str | None = Form(None),
        mock_fail_message: str | None = Form(None),
    ):
        """存档照片并异步发起生成任务；相同幂等键返回原任务而不重复建单。"""
        session_id = resolve_session_id(request)
        pet = db.get_pet(session_id, pet_id)
        if not pet:
            raise HTTPException(404, "宠物档案不存在")

        idem_key = (idempotency_key or idempotency_header or "").strip()
        if not idem_key:
            raise HTTPException(422, "请提供 idempotency_key 以防止重复提交")
        if len(idem_key) > 128:
            raise HTTPException(422, "idempotency_key 长度不能超过 128")

        def reuse_job(existing_job: dict) -> JSONResponse:
            if existing_job["pet_id"] != pet_id:
                raise HTTPException(409, "幂等键已绑定其他宠物，请勿复用")
            return JSONResponse(
                {
                    "reused": True,
                    "job": serialize_job(existing_job, db, session_id),
                    "pet": serialize_pet(db.get_pet(session_id, pet_id) or pet, db, session_id),
                },
                status_code=200,
            )

        existing_job = db.get_job_by_idempotency(session_id, idem_key)
        if existing_job:
            return reuse_job(existing_job)

        # 读取并先存档照片（未传新照片时，允许复用该宠物上次已存档的原照发起重试）
        saved_rel_photo: str
        new_upload_path: Path | None = None
        if photo is not None:
            try:
                raw_bytes = await photo.read(config.max_upload_bytes + 1)
                if len(raw_bytes) > config.max_upload_bytes:
                    raise HTTPException(413, f"上传照片不能超过 {config.max_upload_bytes // 1024 // 1024} MB")
                normalized = await asyncio.to_thread(normalize_photo, raw_bytes)
            except PhotoValidationError as exc:
                raise HTTPException(422, str(exc)) from exc
            finally:
                await photo.close()

            upload_name = f"{uuid.uuid4().hex}.jpg"
            upload_dir = config.data_dir / "uploads" / pet_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            new_upload_path = upload_dir / upload_name
            saved_rel_photo = f"uploads/{pet_id}/{upload_name}"
        elif pet.get("original_photo_path"):
            existing_file = worker.resolve_data_path(pet["original_photo_path"])
            if not existing_file.is_file():
                raise HTTPException(422, "原宠物照片已丢失，请重新上传一张清晰正面照")
            saved_rel_photo = pet["original_photo_path"]
        else:
            raise HTTPException(422, "请上传一张清晰的宠物正面照")

        mock_options: dict = {}
        if config.mock_controls_enabled:
            if mock_delay_seconds is not None:
                mock_options["delay_seconds"] = max(0.05, min(float(mock_delay_seconds), 120.0))
            if mock_fail or mock_fail_stage:
                mock_options["fail_stage"] = mock_fail_stage or "center"
                if mock_fail_message:
                    mock_options["fail_message"] = mock_fail_message[:120]

        try:
            if new_upload_path is not None:
                new_upload_path.write_bytes(normalized)
            job = db.create_generation_job(
                session_id=session_id,
                pet_id=pet_id,
                idempotency_key=idem_key,
                provider=config.provider,
                photo_path=saved_rel_photo,
                mock_options=mock_options,
            )
        except Exception as exc:
            if new_upload_path is not None:
                new_upload_path.unlink(missing_ok=True)
            if isinstance(exc, GenerationKeyConflict):
                return reuse_job(exc.job)
            raise
        worker.enqueue(job["id"])
        updated_pet = db.get_pet(session_id, pet_id) or pet
        return JSONResponse(
            {
                "reused": False,
                "job": serialize_job(job, db, session_id),
                "pet": serialize_pet(updated_pet, db, session_id),
            },
            status_code=202,
        )

    @app.get("/api/generations")
    def list_generations(request: Request):
        session_id = resolve_session_id(request)
        jobs = db.list_jobs(session_id)
        return {"jobs": [serialize_job(item, db, session_id) for item in jobs]}

    @app.get("/api/generations/{job_id}")
    def get_generation(request: Request, job_id: str):
        session_id = resolve_session_id(request)
        job = db.get_job(session_id, job_id)
        if not job:
            raise HTTPException(404, "生成任务不存在")
        return {"job": serialize_job(job, db, session_id)}

    @app.get("/api/current-wallpaper")
    def get_current_wallpaper(request: Request):
        session_id = resolve_session_id(request)
        record = db.get_current_wallpaper(session_id)
        if not record:
            return {"current": None}
        pet = db.get_pet(session_id, record["pet_id"])
        version = db.get_version_for_session(session_id, record["version_id"])
        if not pet or not version:
            return {"current": None}
        return {
            "current": {
                "pet_id": pet["id"],
                "version_id": version["id"],
                "updated_at": record["updated_at"],
                "pet": serialize_pet(pet, db, session_id),
                "assets": serialize_version(version, session_id),
            }
        }

    @app.put("/api/current-wallpaper")
    def put_current_wallpaper(request: Request, body: CurrentWallpaperRequest):
        session_id = resolve_session_id(request)
        pet = db.get_pet(session_id, body.pet_id)
        if not pet:
            raise HTTPException(404, "目标宠物不存在")
        version = db.get_version_for_session(session_id, body.version_id)
        if not version or version["pet_id"] != pet["id"]:
            raise HTTPException(422, "所选素材版本不存在或不属于该宠物")
        if not version["validated"]:
            raise HTTPException(422, "素材版本尚未通过完整性校验")
        saved = db.set_current_wallpaper(session_id, pet["id"], version["id"])
        return {
            "current": {
                "pet_id": pet["id"],
                "version_id": version["id"],
                "updated_at": saved["updated_at"],
                "pet": serialize_pet(pet, db, session_id),
                "assets": serialize_version(version, session_id),
            }
        }

    @app.get("/api/media/pets/{pet_id}/original")
    def get_pet_original_photo(request: Request, pet_id: str):
        session_id = resolve_session_id(request)
        pet = db.get_pet(session_id, pet_id)
        if not pet or not pet.get("original_photo_path"):
            raise HTTPException(404, "宠物照片不存在")
        path = worker.resolve_data_path(pet["original_photo_path"])
        if not path.is_file():
            raise HTTPException(404, "宠物照片文件缺失")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/media/versions/{version_id}/{slot}")
    def get_version_media(
        request: Request,
        version_id: str,
        slot: Literal["idle", "left", "center", "right"],
    ):
        session_id = resolve_session_id(request)
        version = db.get_version_for_session(session_id, version_id)
        if not version:
            raise HTTPException(404, "素材版本不存在")
        if slot == "idle":
            rel_path = version["idle_image_path"]
            media_type = version["idle_meta"].get("mime", "image/jpeg")
        else:
            rel_path = version["actions"][slot]["file_path"]
            media_type = "video/mp4"
        path = worker.resolve_data_path(rel_path)
        if not path.is_file():
            raise HTTPException(404, "媒体文件缺失")
        return FileResponse(path, media_type=media_type)

    # 同源前端静态文件托管
    dist_dir = config.frontend_dist
    index_html = dist_dir / "index.html"
    if (dist_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def serve_root():
        if index_html.is_file():
            return FileResponse(index_html)
        return Response(
            "网页前端尚未构建，请运行 npm run build 或通过 Vite 开发服务器访问。",
            media_type="text/plain; charset=utf-8",
            status_code=200,
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "接口不存在")
        if dist_dir.is_dir():
            dist_root = dist_dir.resolve()
            candidate = (dist_root / full_path).resolve()
            if dist_root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        if index_html.is_file():
            return FileResponse(index_html)
        raise HTTPException(404, "页面不存在")

    return app


app = create_app()
