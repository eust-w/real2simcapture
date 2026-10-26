from __future__ import annotations

import datetime as dt
import fcntl
import io
import json
import re
import shutil
import uuid
import zipfile
from functools import wraps
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from fastapi import HTTPException, UploadFile

from .database import Database
from .materials import resolve_material_metadata
from .rgbd_lifting import lift_depth_pixels, load_depth, pose_for_depth_frame
from .settings import AppSettings


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def serialized_session(function):
    @wraps(function)
    def wrapped(settings, session_id, *args, **kwargs):
        root = live_session_dir(settings, session_id)
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="live_session_not_found")
        # A file lock also serializes independent API worker processes.
        with (root / ".write.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return function(settings, session_id, *args, **kwargs)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    return wrapped


def create_live_session(settings: AppSettings, payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    root = live_session_dir(settings, session_id)
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "depth").mkdir(parents=True, exist_ok=True)
    now = utc_now()
    metadata = {
        "id": session_id,
        "project_id": payload["project_id"],
        "name": payload["name"].strip(),
        "category": payload["category"].strip(),
        "material_category": payload.get("material_category"),
        "mass_kg": payload.get("mass_kg"),
        "friction": payload.get("friction"),
        "status": "recording",
        "frame_count": 0,
        "depth_frame_count": 0,
        "mesh_version": 0,
        "latest_frame_id": None,
        "task_id": None,
        "created_at": now,
        "updated_at": now,
    }
    write_json(root / "poses.json", {"frames": []})
    write_json(root / "capture_manifest.json", capture_manifest(metadata))
    write_json(root / "live_scene.json", empty_live_scene())
    write_json(root / "session.json", metadata)
    return load_live_session(settings, session_id)


def list_live_sessions(settings: AppSettings, project_id: str | None = None) -> list[dict[str, Any]]:
    root = settings.data_dir / "live_sessions"
    if not root.exists():
        return []
    sessions = []
    for session_file in sorted(root.glob("*/session.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            session = load_live_session(settings, session_file.parent.name)
        except FileNotFoundError:
            continue
        if project_id is None or session["project_id"] == project_id:
            sessions.append(session)
    return sessions


def load_live_session(settings: AppSettings, session_id: str) -> dict[str, Any]:
    root = live_session_dir(settings, session_id)
    metadata_path = root / "session.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(session_id)
    metadata = read_json(metadata_path)
    scene = read_json(root / "live_scene.json") if (root / "live_scene.json").is_file() else empty_live_scene()
    return {
        **metadata,
        "scene": scene,
        "mesh_url": f"/api/live-sessions/{session_id}/mesh?version={metadata['mesh_version']}" if metadata.get("mesh_version") else None,
        "capture_root": str(root),
    }


@serialized_session
def append_live_frame(
    settings: AppSettings,
    session_id: str,
    frame_id: str,
    timestamp: float | None,
    tracking_state: str | None,
    transform: str | None,
    intrinsics: str | None,
    image: UploadFile,
    depth: UploadFile | None,
) -> dict[str, Any]:
    root = live_session_dir(settings, session_id)
    metadata = require_recording_session(root)
    safe_id = safe_frame_id(frame_id)

    transform_payload = parse_json_field(transform, "transform", list) if transform else None
    if transform_payload is not None:
        try:
            matrix = np.asarray(transform_payload, dtype=float)
            if matrix.shape != (16,) or not np.isfinite(matrix).all():
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="transform_requires_16_finite_values") from None
    intrinsics_payload = parse_json_field(intrinsics, "intrinsics", dict) if intrinsics else None
    if intrinsics_payload is not None:
        try:
            values = np.asarray([intrinsics_payload[key] for key in ("fx", "fy", "cx", "cy")], dtype=float)
            if not np.isfinite(values).all() or np.any(values[:2] <= 0):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=422, detail="intrinsics_invalid_calibration") from None

    image_suffix = safe_upload_suffix(image.filename, default=".jpg", allowed={".jpg", ".jpeg", ".png"})
    image_path = root / "images" / f"{safe_id}{image_suffix}"
    save_upload(image, image_path)

    depth_ref = None
    if depth is not None:
        depth_suffix = safe_upload_suffix(depth.filename, default=".npy", allowed={".npy", ".png", ".tif", ".tiff"})
        depth_path = root / "depth" / f"{safe_id}{depth_suffix}"
        save_upload(depth, depth_path)
        depth_ref = f"depth/{depth_path.name}"

    if intrinsics_payload is not None:
        write_json(root / "intrinsics.json", intrinsics_payload)

    poses = read_json(root / "poses.json") if (root / "poses.json").is_file() else {"frames": []}
    frames = [frame for frame in poses.get("frames", []) if frame.get("id") != safe_id]
    frames.append(
        {
            "id": safe_id,
            "image": f"images/{image_path.name}",
            "depth": depth_ref,
            "timestamp": timestamp,
            "transform": transform_payload,
            "tracking_state": tracking_state or "unknown",
        }
    )
    frames.sort(key=lambda frame: (frame.get("timestamp") is None, frame.get("timestamp") or 0.0, frame.get("id") or ""))
    write_json(root / "poses.json", {"frames": frames})

    metadata.update(
        {
            "frame_count": len(frames),
            "depth_frame_count": count_depth_frames(root),
            "latest_frame_id": safe_id,
            "updated_at": utc_now(),
        }
    )
    scene = rebuild_live_scene(root, metadata, settings)
    write_json(root / "live_scene.json", scene)
    write_json(root / "capture_manifest.json", capture_manifest(metadata))
    write_json(root / "session.json", metadata)
    return load_live_session(settings, session_id)


@serialized_session
def update_live_mesh(settings: AppSettings, session_id: str, mesh: UploadFile) -> dict[str, Any]:
    root = live_session_dir(settings, session_id)
    metadata = require_recording_session(root)
    payload = mesh.file.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="live_mesh_exceeds_64_mib")
    try:
        geometry = trimesh.load(io.BytesIO(payload), file_type="obj", force="mesh", process=False, skip_materials=True, resolver={})
        if not isinstance(geometry, trimesh.Trimesh) or len(geometry.faces) == 0 or not np.isfinite(geometry.vertices).all():
            raise ValueError()
        if geometry.faces.min() < 0 or geometry.faces.max() >= len(geometry.vertices):
            raise ValueError()
        bounds = geometry.bounds.tolist()
    except Exception:
        raise HTTPException(status_code=422, detail="live_mesh_requires_finite_obj_triangles") from None
    mesh_path = root / "arkit_mesh.obj"
    temporary = root / f".mesh-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(payload)
        temporary.replace(mesh_path)
    finally:
        temporary.unlink(missing_ok=True)
    metadata["mesh_bounds"] = bounds
    metadata["mesh_vertex_count"] = len(geometry.vertices)
    metadata["mesh_face_count"] = len(geometry.faces)
    metadata["mesh_version"] = int(metadata.get("mesh_version") or 0) + 1
    metadata["updated_at"] = utc_now()
    scene = rebuild_live_scene(root, metadata, settings)
    write_json(root / "live_scene.json", scene)
    write_json(root / "capture_manifest.json", capture_manifest(metadata))
    write_json(root / "session.json", metadata)
    return load_live_session(settings, session_id)


def finalize_live_session(
    db: Database,
    settings: AppSettings,
    session_id: str,
    run_pipeline: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    return _finalize_live_session(settings, session_id, db, run_pipeline)


@serialized_session
def _finalize_live_session(settings, session_id, db, run_pipeline):
    root = live_session_dir(settings, session_id)
    metadata = read_json(root / "session.json")
    if metadata.get("task_id"):
        task = db.get_task(metadata["task_id"])
        if task is not None:
            return load_live_session(settings, session_id), task, 200
    if metadata.get("frame_count", 0) <= 0 and metadata.get("mesh_version", 0) <= 0:
        raise HTTPException(status_code=409, detail="live_session_has_no_capture_data")
    if db.get_project(metadata["project_id"]) is None:
        raise HTTPException(status_code=404, detail="project_not_found")

    now = utc_now()
    metadata["updated_at"] = now
    write_json(root / "capture_manifest.json", capture_manifest({**metadata, "status": "finalized"}))

    task_id = str(uuid.uuid4())
    task_dir = settings.data_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    input_path = task_dir / "live_capture.zip"
    zip_capture_root(root, input_path)
    task = {
        "id": task_id,
        "project_id": metadata["project_id"],
        "name": metadata["name"],
        "mode": "scene",
        "category": metadata["category"],
        "material_category": metadata.get("material_category"),
        "status": "queued",
        "input_path": str(input_path),
        "original_filename": input_path.name,
        "mass_kg": metadata.get("mass_kg"),
        "friction": metadata.get("friction"),
        "failure_reason": None,
        "logs": [f"{now} finalized live session {session_id} into {input_path.name}"],
        "report": {"live_session_id": session_id, "live_scene": read_json(root / "live_scene.json")},
        "scene": None,
        "artifacts": [],
        "created_at": now,
        "updated_at": now,
    }
    created = db.create_task(task)
    metadata["task_id"] = task_id
    metadata["status"] = "finalized"
    write_json(root / "session.json", metadata)
    session = load_live_session(settings, session_id)
    if not run_pipeline:
        return session, created, 201

    from .pipeline import run_task

    completed, status_code = run_task(db, settings, task_id)
    return session, completed, status_code


def rebuild_live_scene(root: Path, metadata: dict[str, Any], settings: AppSettings) -> dict[str, Any]:
    has_mesh = bool(metadata.get("mesh_bounds"))
    points = np.asarray(metadata["mesh_bounds"], dtype=float) if has_mesh else collect_live_points(root)
    source_kind = "live_arkit_mesh" if has_mesh else "live_rgbd_depth_bounds"
    if points.size == 0:
        points = read_obj_vertices(root / "arkit_mesh.obj")
        source_kind = "live_arkit_mesh_bounds"
    if points.size == 0:
        return empty_live_scene(source_kind=source_kind, frame_count=int(metadata.get("frame_count") or 0), depth_frame_count=int(metadata.get("depth_frame_count") or 0))

    bounds_min = points.min(axis=0)
    bounds_max = points.max(axis=0)
    dimensions = np.maximum(bounds_max - bounds_min, np.array([0.01, 0.01, 0.01], dtype=float))
    center = (bounds_min + bounds_max) / 2.0
    volume = float(np.prod(dimensions))
    mass_kg = float(metadata["mass_kg"]) if metadata.get("mass_kg") is not None else max(volume * settings.default_density_kg_m3, 0.001)
    friction = float(metadata["friction"]) if metadata.get("friction") is not None else settings.default_friction
    material = resolve_material_metadata(metadata.get("category"), {"material_category": metadata.get("material_category")})
    inertia = [
        mass_kg * (dimensions[1] ** 2 + dimensions[2] ** 2) / 12.0,
        mass_kg * (dimensions[0] ** 2 + dimensions[2] ** 2) / 12.0,
        mass_kg * (dimensions[0] ** 2 + dimensions[1] ** 2) / 12.0,
    ]
    frame_count = int(metadata.get("frame_count") or 0)
    depth_frame_count = int(metadata.get("depth_frame_count") or 0)
    return {
        "unit": "meter",
        "up_axis": "z",
        "source_kind": source_kind,
        "objects": [
            {
                "id": "live_scene_001",
                "name": metadata.get("name") or "Live Scene",
                "category": metadata.get("category") or "scene",
                **material,
                "visual_mesh": "arkit_mesh.obj" if has_mesh else None,
                "collision_mesh": None,
                "pose": {"position": [round_float(value) for value in center.tolist()], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "scale": [1.0, 1.0, 1.0],
                "dimensions": [round_float(value) for value in dimensions.tolist()],
                "mass_kg": round_float(mass_kg),
                "friction": round_float(friction),
                "inertia_diagonal": [round_float(value) for value in inertia],
                "confidence": {
                    "geometry": round_float(min(1.0, max(depth_frame_count, frame_count) / 8.0)),
                    "segmentation": 0.2,
                    "material": 0.3 if metadata.get("material_category") is None else 0.7,
                },
                "live_metrics": {
                    "frame_count": frame_count,
                    "depth_frame_count": depth_frame_count,
                    "point_count": int(points.shape[0]),
                    "mesh_version": int(metadata.get("mesh_version") or 0),
                },
            }
        ],
        "metrics": {
            "frame_count": frame_count,
            "depth_frame_count": depth_frame_count,
            "point_count": metadata.get("mesh_vertex_count", int(points.shape[0])),
            "face_count": metadata.get("mesh_face_count", 0),
            "updated_at": utc_now(),
        },
    }


def collect_live_points(root: Path) -> np.ndarray:
    intrinsics_path = root / "intrinsics.json"
    depth_dir = root / "depth"
    if not intrinsics_path.is_file() or not depth_dir.is_dir():
        return np.zeros((0, 3), dtype=float)
    intrinsics = read_json(intrinsics_path)
    poses = read_json(root / "poses.json") if (root / "poses.json").is_file() else {"frames": []}
    pose_by_id = {frame["id"]: frame.get("transform") for frame in poses.get("frames", []) if frame.get("transform") is not None}
    point_sets: list[np.ndarray] = []
    # Bounds are a lightweight recent-frame fallback until ARKit supplies a mesh.
    for depth_path in sorted(depth_dir.iterdir())[-12:]:
        if depth_path.suffix.lower() not in {".npy", ".png", ".tif", ".tiff"}:
            continue
        try:
            depth = load_depth(depth_path, float(intrinsics.get("depth_scale", 1.0)))
            points, _rows, _cols = lift_depth_pixels(depth, intrinsics, pose_for_depth_frame(depth_path, pose_by_id))
        except Exception:
            continue
        if points.size == 0:
            continue
        stride = max(1, points.shape[0] // 4000)
        point_sets.append(points[::stride])
    if not point_sets:
        return np.zeros((0, 3), dtype=float)
    return np.concatenate(point_sets, axis=0)


def read_obj_vertices(path: Path) -> np.ndarray:
    if not path.is_file():
        return np.zeros((0, 3), dtype=float)
    vertices: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("v "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
        except ValueError:
            continue
    if not vertices:
        return np.zeros((0, 3), dtype=float)
    return np.array(vertices, dtype=float)


def zip_capture_root(root: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    excluded = {root / "session.json", root / "live_scene.json"}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path in excluded or path.name.startswith("."):
                continue
            archive.write(path, path.relative_to(root).as_posix())


def live_session_dir(settings: AppSettings, session_id: str) -> Path:
    safe_id = safe_uuid_like(session_id)
    return settings.data_dir / "live_sessions" / safe_id


def require_recording_session(root: Path) -> dict[str, Any]:
    metadata_path = root / "session.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="live_session_not_found")
    metadata = read_json(metadata_path)
    if metadata.get("status") != "recording":
        raise HTTPException(status_code=409, detail="live_session_not_recording")
    return metadata


def count_depth_frames(root: Path) -> int:
    depth_dir = root / "depth"
    if not depth_dir.is_dir():
        return 0
    return sum(1 for path in depth_dir.iterdir() if path.is_file() and path.suffix.lower() in {".npy", ".png", ".tif", ".tiff"})


def capture_manifest(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "scene",
        "source": "Real2Sim live ARKit RGB-D stream",
        "live_session_id": metadata["id"],
        "created_at": metadata["created_at"],
        "updated_at": metadata["updated_at"],
        "frame_count": metadata.get("frame_count", 0),
        "depth_frame_count": metadata.get("depth_frame_count", 0),
        "mesh_version": metadata.get("mesh_version", 0),
        "status": metadata.get("status", "recording"),
    }


def empty_live_scene(source_kind: str = "live_rgbd_depth_bounds", frame_count: int = 0, depth_frame_count: int = 0) -> dict[str, Any]:
    return {
        "unit": "meter",
        "up_axis": "z",
        "source_kind": source_kind,
        "objects": [],
        "metrics": {
            "frame_count": frame_count,
            "depth_frame_count": depth_frame_count,
            "point_count": 0,
            "updated_at": utc_now(),
        },
    }


def parse_json_field(raw: str, field_name: str, expected_type: type) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name}_invalid_json") from exc
    if not isinstance(value, expected_type):
        raise HTTPException(status_code=422, detail=f"{field_name}_invalid_type")
    return value


def save_upload(upload: UploadFile, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            total = 0
            while chunk := upload.file.read(1024 * 1024):
                total += len(chunk)
                if total > 64 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="live_upload_exceeds_64_mib")
                output.write(chunk)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def safe_frame_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return safe or f"frame_{uuid.uuid4().hex}"


def safe_uuid_like(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9-]+", "", value)
    if not safe:
        raise HTTPException(status_code=404, detail="live_session_not_found")
    return safe


def safe_upload_suffix(filename: str | None, default: str, allowed: set[str]) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in allowed else default


def round_float(value: float) -> float:
    return round(float(value), 6)
