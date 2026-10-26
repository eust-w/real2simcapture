from __future__ import annotations

import datetime as dt
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .database import Database, database_health
from .dependencies import check_dependencies
from .exporters import generate_roomplan_package, generate_standalone_object_package, regenerate_metadata_exports
from .live_sessions import (
    append_live_frame,
    create_live_session as create_live_session_record,
    finalize_live_session as finalize_live_session_record,
    list_live_sessions as list_live_session_records,
    load_live_session,
    live_session_dir,
    update_live_mesh,
)
from .materials import resolve_material_metadata
from .package_validation import validate_export_package
from .pipeline import PipelineError, find_scene_segmentation_with_error, run_task
from .queue import enqueue_task, queue_health
from .reconstruction_providers import reconstruction_health
from .segmentation import segmentation_health
from .simulator_adapters import simulator_adapters_health
from .settings import AppSettings
from .storage import LocalStorage, storage_health
from .storage import publish_artifacts_to_storage


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


class LiveSessionCreate(BaseModel):
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    material_category: str | None = None
    mass_kg: float | None = Field(default=None, gt=0)
    friction: float | None = Field(default=None, ge=0)


class ObjectPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    material_category: str | None = None
    mass_kg: float | None = Field(default=None, gt=0)
    friction: float | None = Field(default=None, ge=0)


class ObjectSplit(BaseModel):
    axis: str = Field(default="x", pattern="^[xyz]$")
    left_name: str | None = None
    right_name: str | None = None


class ObjectMerge(BaseModel):
    object_ids: list[str] = Field(min_length=2)
    name: str
    category: str
    material_category: str | None = None


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_url, settings.database_connect_timeout_seconds)

    app = FastAPI(title="real2simcapture API", version="0.1.0")
    app.state.settings = settings
    app.state.db = db
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_db() -> Database:
        return app.state.db

    def get_settings() -> AppSettings:
        return app.state.settings

    @app.get("/api/health")
    def health(settings: AppSettings = Depends(get_settings)) -> dict[str, Any]:
        return {
            "status": "ok",
            "storage": {
                "data_dir": str(settings.data_dir.resolve()),
                "output_dir": str(settings.output_dir.resolve()),
            },
            "dependencies": check_dependencies(settings.dependency_tools),
            "database": database_health(settings.database_url, settings.database_connect_timeout_seconds),
            "queue": queue_health(settings),
            "storage_backend": storage_health(settings),
            "reconstruction": reconstruction_health(settings),
            "segmentation": segmentation_health(settings),
            "simulators": simulator_adapters_health(settings),
        }

    @app.post("/api/projects", status_code=201)
    def create_project(payload: ProjectCreate, db: Database = Depends(get_db)) -> dict[str, Any]:
        project = {
            "id": str(uuid.uuid4()),
            "name": payload.name.strip(),
            "description": payload.description.strip(),
            "created_at": utc_now(),
        }
        return db.create_project(project)

    @app.get("/api/projects")
    def list_projects(db: Database = Depends(get_db)) -> list[dict[str, Any]]:
        return db.list_projects()

    @app.get("/api/tasks")
    def list_tasks(project_id: str | None = None, db: Database = Depends(get_db)) -> list[dict[str, Any]]:
        return [serialize_task(task) for task in db.list_tasks(project_id)]

    @app.get("/api/live-sessions")
    def list_live_sessions(project_id: str | None = None, settings: AppSettings = Depends(get_settings)) -> list[dict[str, Any]]:
        return list_live_session_records(settings, project_id)

    @app.post("/api/live-sessions", status_code=201)
    def create_live_session(
        payload: LiveSessionCreate,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        if db.get_project(payload.project_id) is None:
            raise HTTPException(status_code=404, detail="project_not_found")
        return create_live_session_record(settings, payload.model_dump())

    @app.get("/api/live-sessions/{session_id}")
    def get_live_session(session_id: str, settings: AppSettings = Depends(get_settings)) -> dict[str, Any]:
        try:
            return load_live_session(settings, session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="live_session_not_found") from None

    @app.post("/api/live-sessions/{session_id}/frames")
    def append_live_session_frame(
        session_id: str,
        frame_id: str = Form(...),
        timestamp: float | None = Form(default=None),
        tracking_state: str | None = Form(default=None),
        transform: str | None = Form(default=None),
        intrinsics: str | None = Form(default=None),
        image: UploadFile = File(...),
        depth: UploadFile | None = File(default=None),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        return append_live_frame(
            settings=settings,
            session_id=session_id,
            frame_id=frame_id,
            timestamp=timestamp,
            tracking_state=tracking_state,
            transform=transform,
            intrinsics=intrinsics,
            image=image,
            depth=depth,
        )

    @app.post("/api/live-sessions/{session_id}/mesh")
    def upload_live_session_mesh(
        session_id: str,
        mesh: UploadFile = File(...),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        return update_live_mesh(settings, session_id, mesh)

    @app.get("/api/live-sessions/{session_id}/mesh")
    def download_live_mesh(session_id: str, settings: AppSettings = Depends(get_settings)) -> Response:
        mesh_path = live_session_dir(settings, session_id) / "arkit_mesh.obj"
        if not mesh_path.is_file():
            raise HTTPException(status_code=404, detail="live_mesh_not_available")
        return Response(mesh_path.read_bytes(), media_type="text/plain", headers={"Cache-Control": "no-store"})

    @app.post("/api/live-sessions/{session_id}/finalize")
    def finalize_live_session(
        session_id: str,
        run: bool = False,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> JSONResponse:
        try:
            session, task, status_code = finalize_live_session_record(db, settings, session_id, run_pipeline=run)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="live_session_not_found") from None
        return JSONResponse(status_code=status_code, content={"session": session, "task": serialize_task(task)})

    @app.post("/api/tasks", status_code=201)
    def create_task(
        project_id: str = Form(...),
        name: str = Form(...),
        mode: str = Form(...),
        category: str = Form(...),
        material_category: str | None = Form(default=None),
        mass_kg: float | None = Form(default=None),
        friction: float | None = Form(default=None),
        capture: UploadFile = File(...),
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        if db.get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="project_not_found")
        if mode not in {"asset", "scene"}:
            raise HTTPException(status_code=422, detail="mode must be asset or scene")

        task_id = str(uuid.uuid4())
        task_dir = settings.data_dir / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        filename = safe_filename(capture.filename or "capture.bin")
        input_path = task_dir / filename
        with input_path.open("wb") as target:
            shutil.copyfileobj(capture.file, target)
        now = utc_now()
        task = {
            "id": task_id,
            "project_id": project_id,
            "name": name.strip(),
            "mode": mode,
            "category": category.strip(),
            "material_category": material_category.strip() if material_category and material_category.strip() else None,
            "status": "queued",
            "input_path": str(input_path),
            "original_filename": filename,
            "mass_kg": mass_kg,
            "friction": friction,
            "failure_reason": None,
            "logs": [f"{now} uploaded {filename}"],
            "report": None,
            "scene": None,
            "artifacts": [],
            "created_at": now,
            "updated_at": now,
        }
        return serialize_task(db.create_task(task))

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        task = db.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        return serialize_task(task)

    @app.post("/api/tasks/{task_id}/run")
    def run_task_endpoint(
        task_id: str,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> JSONResponse:
        if db.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        task, status_code = run_task(db, settings, task_id)
        return JSONResponse(status_code=status_code, content=serialize_task(task))

    @app.post("/api/tasks/{task_id}/verify-simulation")
    def verify_simulation_package(
        task_id: str,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        task = db.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        if task["status"] != "completed":
            raise HTTPException(status_code=409, detail="task_not_completed")
        output_dir = settings.output_dir / task_id
        validation = validate_export_package(output_dir, settings)
        report = {**(task.get("report") or {}), "package_validation": validation}
        (output_dir / "report.json").write_text(json_dumps_pretty(report), encoding="utf-8")
        artifacts = publish_artifacts_to_storage(
            storage_backend=settings.storage_backend,
            storage_dir=settings.storage_dir,
            public_base_url=settings.public_base_url,
            s3_bucket=settings.s3_bucket,
            s3_endpoint_url=settings.s3_endpoint_url,
            s3_access_key_id=settings.s3_access_key_id,
            s3_secret_access_key=settings.s3_secret_access_key,
            s3_public_base_url=settings.s3_public_base_url,
            task_id=task_id,
            output_dir=output_dir,
            artifacts=task.get("artifacts", []),
        )
        updated = db.update_task(
            task_id,
            report=report,
            artifacts=artifacts,
            logs=[*task.get("logs", []), f"{utc_now()} simulation package verification valid={validation['valid']}"],
            updated_at=utc_now(),
        )
        return serialize_task(updated)

    @app.post("/api/tasks/{task_id}/scene/objects/{object_id}/export")
    def export_scene_object(
        task_id: str,
        object_id: str,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> FileResponse:
        task = require_completed_scene_task(db, task_id)
        try:
            package_path = generate_standalone_object_package(
                task=task,
                object_id=object_id,
                task_output_dir=settings.output_dir / task_id,
                export_dir=settings.output_dir / "object_exports" / task_id / safe_filename(object_id),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="object_not_found") from None
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=f"object_asset_missing:{exc}") from exc
        return FileResponse(
            package_path,
            media_type="application/zip",
            filename=f"{safe_filename(object_id)}_real2sim_package.zip",
        )

    @app.post("/api/tasks/{task_id}/enqueue", status_code=202)
    def enqueue_task_endpoint(
        task_id: str,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> JSONResponse:
        task = db.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        if task["status"] == "failed":
            task = db.update_task(
                task_id,
                status="queued",
                failure_reason=None,
                logs=[*task.get("logs", []), f"{utc_now()} failed task requeued"],
                updated_at=utc_now(),
            )
        elif task["status"] != "queued":
            raise HTTPException(status_code=409, detail="task_not_runnable")
        result = enqueue_task(settings, task_id)
        if not result.ok:
            return JSONResponse(
                status_code=503,
                content={**serialize_task(task), "queue": {"backend": result.backend, "ok": False, "reason": result.reason}},
            )
        return JSONResponse(
            status_code=202,
            content={**serialize_task(task), "queue": {"backend": result.backend, "ok": True, "reason": None}},
        )

    @app.patch("/api/tasks/{task_id}/scene/objects/{object_id}")
    def patch_scene_object(
        task_id: str,
        object_id: str,
        payload: ObjectPatch,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        task = db.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        if task["status"] != "completed" or not task.get("scene"):
            raise HTTPException(status_code=409, detail="task_has_no_completed_scene")
        scene = task["scene"]
        objects = scene.get("objects", [])
        target = next((obj for obj in objects if obj["id"] == object_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="object_not_found")
        if payload.name is not None:
            target["name"] = payload.name.strip()
        if payload.category is not None:
            target["category"] = payload.category.strip()
        if payload.material_category is not None:
            target.update(resolve_material_metadata(target.get("category"), {"material_category": payload.material_category}))
        elif payload.category is not None and target.get("material_category_source") in {None, "category_prior", "not_provided"}:
            target.update(resolve_material_metadata(target.get("category"), target))
        if payload.mass_kg is not None:
            target["mass_kg"] = payload.mass_kg
        if payload.friction is not None:
            target["friction"] = payload.friction

        task["scene"] = scene
        result = regenerate_metadata_exports(
            task=task,
            output_dir=settings.output_dir / task_id,
            public_base_url=settings.public_base_url,
        )
        artifacts = publish_artifacts_to_storage(
            storage_backend=settings.storage_backend,
            storage_dir=settings.storage_dir,
            public_base_url=settings.public_base_url,
            s3_bucket=settings.s3_bucket,
            s3_endpoint_url=settings.s3_endpoint_url,
            s3_access_key_id=settings.s3_access_key_id,
            s3_secret_access_key=settings.s3_secret_access_key,
            s3_public_base_url=settings.s3_public_base_url,
            task_id=task_id,
            output_dir=settings.output_dir / task_id,
            artifacts=result["artifacts"],
        )
        updated = db.update_task(
            task_id,
            scene=result["scene"],
            report=result["report"],
            artifacts=artifacts,
            logs=[*task.get("logs", []), f"{utc_now()} scene object {object_id} updated and exports regenerated"],
            updated_at=utc_now(),
        )
        return serialize_task(updated)

    @app.delete("/api/tasks/{task_id}/scene/objects/{object_id}")
    def delete_scene_object(
        task_id: str,
        object_id: str,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        task = require_completed_scene_task(db, task_id)
        scene = task["scene"]
        before = len(scene.get("objects", []))
        scene["objects"] = [obj for obj in scene.get("objects", []) if obj["id"] != object_id]
        if len(scene["objects"]) == before:
            raise HTTPException(status_code=404, detail="object_not_found")
        if not scene["objects"]:
            raise HTTPException(status_code=409, detail="scene_requires_at_least_one_object")
        return update_scene_and_exports(db, settings, task, scene, f"scene object {object_id} deleted and exports regenerated")

    @app.post("/api/tasks/{task_id}/scene/objects/{object_id}/split")
    def split_scene_object(
        task_id: str,
        object_id: str,
        payload: ObjectSplit,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        task = require_completed_scene_task(db, task_id)
        scene = task["scene"]
        objects = scene.get("objects", [])
        index = next((idx for idx, obj in enumerate(objects) if obj["id"] == object_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail="object_not_found")
        source = objects[index]
        if "dimensions" not in source:
            raise HTTPException(status_code=409, detail="object_has_no_parametric_dimensions")

        axis_index = {"x": 0, "y": 1, "z": 2}[payload.axis]
        dimensions = [float(value) for value in source["dimensions"]]
        if dimensions[axis_index] <= 0.002:
            raise HTTPException(status_code=409, detail="object_too_small_to_split")
        half = dimensions[axis_index] / 2.0
        child_dimensions = dimensions[:]
        child_dimensions[axis_index] = half
        offset = half / 2.0
        base_position = [float(value) for value in source["pose"]["position"]]
        left_position = base_position[:]
        right_position = base_position[:]
        left_position[axis_index] -= offset
        right_position[axis_index] += offset
        mass = float(source["mass_kg"]) / 2.0
        left = clone_parametric_object(source, f"{object_id}_a", payload.left_name or f"{source['name']} A", child_dimensions, left_position, mass)
        right = clone_parametric_object(source, f"{object_id}_b", payload.right_name or f"{source['name']} B", child_dimensions, right_position, mass)
        scene["objects"] = [*objects[:index], left, right, *objects[index + 1 :]]
        return update_scene_and_exports(db, settings, task, scene, f"scene object {object_id} split on {payload.axis} and exports regenerated")

    @app.post("/api/tasks/{task_id}/scene/objects/merge")
    def merge_scene_objects(
        task_id: str,
        payload: ObjectMerge,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> dict[str, Any]:
        task = require_completed_scene_task(db, task_id)
        scene = task["scene"]
        objects = scene.get("objects", [])
        selected = [obj for obj in objects if obj["id"] in payload.object_ids]
        if len(selected) != len(set(payload.object_ids)):
            raise HTTPException(status_code=404, detail="object_not_found")
        if any("dimensions" not in obj for obj in selected):
            raise HTTPException(status_code=409, detail="object_has_no_parametric_dimensions")

        bounds_min = [min(obj["pose"]["position"][axis] - obj["dimensions"][axis] / 2.0 for obj in selected) for axis in range(3)]
        bounds_max = [max(obj["pose"]["position"][axis] + obj["dimensions"][axis] / 2.0 for obj in selected) for axis in range(3)]
        dimensions = [bounds_max[axis] - bounds_min[axis] for axis in range(3)]
        position = [(bounds_min[axis] + bounds_max[axis]) / 2.0 for axis in range(3)]
        merged_id = safe_identifier(payload.name)
        mass = sum(float(obj["mass_kg"]) for obj in selected)
        friction = sum(float(obj["friction"]) for obj in selected) / len(selected)
        merged = clone_parametric_object(
            selected[0],
            merged_id,
            payload.name.strip(),
            dimensions,
            position,
            mass,
            category=payload.category.strip(),
            material_category=payload.material_category,
            friction=friction,
        )
        remaining = [obj for obj in objects if obj["id"] not in set(payload.object_ids)]
        scene["objects"] = [*remaining, merged]
        return update_scene_and_exports(db, settings, task, scene, f"scene objects {','.join(payload.object_ids)} merged and exports regenerated")

    @app.post("/api/tasks/{task_id}/scene/resegment")
    def resegment_scene(
        task_id: str,
        db: Database = Depends(get_db),
        settings: AppSettings = Depends(get_settings),
    ) -> JSONResponse:
        task = require_completed_scene_task(db, task_id)
        if task["mode"] != "scene":
            raise HTTPException(status_code=409, detail="task_is_not_scene_mode")
        now = utc_now()
        logs = [*task.get("logs", []), f"{now} resegmenting scene from original capture with provider={settings.segmentation_provider}"]
        work_dir = settings.data_dir / "tasks" / task_id / "resegment"
        try:
            segmented_scene = find_scene_segmentation_with_error(
                input_path=Path(task["input_path"]),
                work_dir=work_dir,
                default_category=task["category"],
                mode=task["mode"],
                settings=settings,
                logs=logs,
            )
        except PipelineError as exc:
            report = {
                **(task.get("report") or {}),
                "last_resegment": {"valid": False, "provider": settings.segmentation_provider, "reason": exc.reason, "completed_at": utc_now()},
            }
            updated = db.update_task(
                task_id,
                report=report,
                logs=[*logs, *exc.logs, f"{utc_now()} resegment failed: {exc.reason}"],
                updated_at=utc_now(),
            )
            return JSONResponse(status_code=409, content=serialize_task(updated))

        if segmented_scene is None:
            report = {
                **(task.get("report") or {}),
                "last_resegment": {
                    "valid": False,
                    "provider": settings.segmentation_provider,
                    "reason": "segmentation_source_not_found",
                    "completed_at": utc_now(),
                },
            }
            updated = db.update_task(
                task_id,
                report=report,
                logs=[*logs, f"{utc_now()} resegment failed: segmentation_source_not_found"],
                updated_at=utc_now(),
            )
            return JSONResponse(status_code=409, content=serialize_task(updated))

        result = generate_roomplan_package(
            task=task,
            roomplan=segmented_scene,
            output_dir=settings.output_dir / task_id,
            public_base_url=settings.public_base_url,
            default_density_kg_m3=settings.default_density_kg_m3,
            default_friction=settings.default_friction,
        )
        report = {
            **result["report"],
            "last_resegment": {"valid": True, "provider": settings.segmentation_provider, "completed_at": utc_now()},
        }
        (settings.output_dir / task_id / "report.json").write_text(json_dumps_pretty(report), encoding="utf-8")
        try:
            artifacts = publish_artifacts_to_storage(
                storage_backend=settings.storage_backend,
                storage_dir=settings.storage_dir,
                public_base_url=settings.public_base_url,
                s3_bucket=settings.s3_bucket,
                s3_endpoint_url=settings.s3_endpoint_url,
                s3_access_key_id=settings.s3_access_key_id,
                s3_secret_access_key=settings.s3_secret_access_key,
                s3_public_base_url=settings.s3_public_base_url,
                task_id=task_id,
                output_dir=settings.output_dir / task_id,
                artifacts=result["artifacts"],
            )
        except Exception as exc:
            failed_report = {
                **report,
                "last_resegment": {
                    "valid": False,
                    "provider": settings.segmentation_provider,
                    "reason": "artifact_publish_failed",
                    "completed_at": utc_now(),
                },
            }
            updated = db.update_task(
                task_id,
                report=failed_report,
                logs=[*logs, f"{utc_now()} resegment artifact publish failed: {type(exc).__name__}: {exc}"],
                updated_at=utc_now(),
            )
            return JSONResponse(status_code=502, content=serialize_task(updated))
        updated = db.update_task(
            task_id,
            scene=result["scene"],
            report=report,
            artifacts=artifacts,
            logs=[*logs, f"{utc_now()} scene resegmented and exports regenerated"],
            updated_at=utc_now(),
        )
        return JSONResponse(status_code=200, content=serialize_task(updated))

    @app.get("/api/artifacts/{task_id}/{artifact_path:path}")
    def get_artifact(task_id: str, artifact_path: str, settings: AppSettings = Depends(get_settings)) -> FileResponse:
        root = (settings.output_dir / task_id).resolve()
        path = (root / artifact_path).resolve()
        if root not in [path, *path.parents] or not path.is_file():
            raise HTTPException(status_code=404, detail="artifact_not_found")
        return FileResponse(path)

    @app.get("/api/storage/{storage_key:path}")
    def get_storage_object(storage_key: str, settings: AppSettings = Depends(get_settings)) -> FileResponse:
        if settings.storage_backend != "local":
            raise HTTPException(status_code=404, detail="storage_object_not_local")
        storage = LocalStorage(settings.storage_dir, settings.public_base_url)
        try:
            path = storage.open_file(storage_key)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="storage_object_not_found") from None
        return FileResponse(path)

    return app


def serialize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "project_id": task["project_id"],
        "name": task["name"],
        "mode": task["mode"],
        "category": task["category"],
        "material_category": task.get("material_category"),
        "status": task["status"],
        "original_filename": task["original_filename"],
        "mass_kg": task.get("mass_kg"),
        "friction": task.get("friction"),
        "failure_reason": task.get("failure_reason"),
        "logs": task.get("logs", []),
        "report": task.get("report"),
        "scene": task.get("scene"),
        "artifacts": task.get("artifacts", []),
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


def json_dumps_pretty(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe or "capture.bin"


def safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower() or "object"


def require_completed_scene_task(db: Database, task_id: str) -> dict[str, Any]:
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    if task["status"] != "completed" or not task.get("scene"):
        raise HTTPException(status_code=409, detail="task_has_no_completed_scene")
    return task


def update_scene_and_exports(
    db: Database,
    settings: AppSettings,
    task: dict[str, Any],
    scene: dict[str, Any],
    log_message: str,
) -> dict[str, Any]:
    task["scene"] = scene
    result = regenerate_metadata_exports(
        task=task,
        output_dir=settings.output_dir / task["id"],
        public_base_url=settings.public_base_url,
    )
    artifacts = publish_artifacts_to_storage(
        storage_backend=settings.storage_backend,
        storage_dir=settings.storage_dir,
        public_base_url=settings.public_base_url,
        s3_bucket=settings.s3_bucket,
        s3_endpoint_url=settings.s3_endpoint_url,
        s3_access_key_id=settings.s3_access_key_id,
        s3_secret_access_key=settings.s3_secret_access_key,
        s3_public_base_url=settings.s3_public_base_url,
        task_id=task["id"],
        output_dir=settings.output_dir / task["id"],
        artifacts=result["artifacts"],
    )
    updated = db.update_task(
        task["id"],
        scene=result["scene"],
        report=result["report"],
        artifacts=artifacts,
        logs=[*task.get("logs", []), f"{utc_now()} {log_message}"],
        updated_at=utc_now(),
    )
    return serialize_task(updated)


def clone_parametric_object(
    source: dict[str, Any],
    object_id: str,
    name: str,
    dimensions: list[float],
    position: list[float],
    mass_kg: float,
    category: str | None = None,
    material_category: str | None = None,
    friction: float | None = None,
) -> dict[str, Any]:
    cloned = {**source}
    cloned["id"] = object_id
    cloned["name"] = name
    cloned["category"] = category or source["category"]
    if material_category is not None:
        cloned.update(resolve_material_metadata(cloned["category"], {"material_category": material_category}))
    elif category is not None and source.get("material_category_source") in {None, "category_prior", "not_provided"}:
        cloned.update(resolve_material_metadata(cloned["category"], source))
    cloned["dimensions"] = [float(value) for value in dimensions]
    cloned["pose"] = {
        "position": [float(value) for value in position],
        "quaternion": source["pose"].get("quaternion", [1.0, 0.0, 0.0, 0.0]),
    }
    cloned["mass_kg"] = float(mass_kg)
    cloned["friction"] = float(friction if friction is not None else source["friction"])
    cloned["inertia_diagonal"] = [
        cloned["mass_kg"] * (cloned["dimensions"][1] ** 2 + cloned["dimensions"][2] ** 2) / 12.0,
        cloned["mass_kg"] * (cloned["dimensions"][0] ** 2 + cloned["dimensions"][2] ** 2) / 12.0,
        cloned["mass_kg"] * (cloned["dimensions"][0] ** 2 + cloned["dimensions"][1] ** 2) / 12.0,
    ]
    return cloned


app = create_app()
