from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import Database
from .dependencies import missing_tools
from .exporters import find_mesh_in_capture, generate_package, generate_roomplan_package
from .quality import analyze_capture_quality
from .reconstruction_providers import ReconstructionProviderError, run_external_reconstruction_provider
from .rgbd_lifting import RGBDLiftingError, find_rgbd_scene_in_capture
from .segmentation import SegmentationProviderError, find_sam2_scene_in_capture
from .settings import AppSettings
from .storage import publish_artifacts_to_storage


class PipelineError(Exception):
    def __init__(self, reason: str, logs: list[str], report: dict[str, Any] | None = None):
        self.reason = reason
        self.logs = logs
        self.report = report
        super().__init__(reason)


@dataclass(frozen=True)
class PhotogrammetryResult:
    mesh_path: Path
    capture_quality: dict[str, Any]


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def run_task(db: Database, settings: AppSettings, task_id: str) -> tuple[dict[str, Any], int]:
    task = db.get_task(task_id)
    if task is None:
        raise KeyError(task_id)

    logs = [*task.get("logs", []), f"{utc_now()} starting real pipeline for task {task_id}"]
    task = db.update_task(task_id, status="running", logs=logs, failure_reason=None, updated_at=utc_now())
    output_dir = settings.output_dir / task_id
    input_path = Path(task["input_path"])

    try:
        roomplan = find_roomplan_json_in_capture(input_path, settings.data_dir / "tasks" / task_id)
        rgbd_scene = (
            None
            if roomplan is not None
            else find_scene_segmentation_with_error(
                input_path=input_path,
                work_dir=settings.data_dir / "tasks" / task_id,
                default_category=task["category"],
                mode=task["mode"],
                settings=settings,
                logs=logs,
            )
        )
        mesh_path = None if roomplan is not None or rgbd_scene is not None else find_mesh_in_capture(input_path, settings.data_dir / "tasks" / task_id)
        if roomplan is not None:
            result = generate_roomplan_package(
                task=task,
                roomplan=roomplan,
                output_dir=output_dir,
                public_base_url=settings.public_base_url,
                default_density_kg_m3=settings.default_density_kg_m3,
                default_friction=settings.default_friction,
            )
        elif rgbd_scene is not None:
            result = generate_roomplan_package(
                task=task,
                roomplan=rgbd_scene,
                output_dir=output_dir,
                public_base_url=settings.public_base_url,
                default_density_kg_m3=settings.default_density_kg_m3,
                default_friction=settings.default_friction,
            )
        elif mesh_path is None:
            photogrammetry = run_photogrammetry_capture(task, settings, output_dir, logs)
            result = generate_package(
                task=task,
                mesh_path=photogrammetry.mesh_path,
                output_dir=output_dir,
                public_base_url=settings.public_base_url,
                default_density_kg_m3=settings.default_density_kg_m3,
                default_friction=settings.default_friction,
                capture_quality=photogrammetry.capture_quality,
            )
        else:
            result = generate_package(
                task=task,
                mesh_path=mesh_path,
                output_dir=output_dir,
                public_base_url=settings.public_base_url,
                default_density_kg_m3=settings.default_density_kg_m3,
                default_friction=settings.default_friction,
            )
    except PipelineError as exc:
        failed_logs = [*logs, *exc.logs, f"{utc_now()} failed: {exc.reason}"]
        return (
            db.update_task(
                task_id,
                status="failed",
                failure_reason=exc.reason,
                logs=failed_logs,
                artifacts=[],
                report=exc.report,
                updated_at=utc_now(),
            ),
            409,
        )
    except Exception as exc:
        failed_logs = [*logs, f"{utc_now()} failed: {type(exc).__name__}: {exc}"]
        return (
            db.update_task(
                task_id,
                status="failed",
                failure_reason="pipeline_failed",
                logs=failed_logs,
                artifacts=[],
                updated_at=utc_now(),
            ),
            500,
        )

    completed_logs = [*logs, f"{utc_now()} generated {len(result['artifacts'])} artifacts"]
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
            output_dir=output_dir,
            artifacts=result["artifacts"],
        )
    except Exception as exc:
        failed_logs = [*completed_logs, f"{utc_now()} artifact publish failed: {type(exc).__name__}: {exc}"]
        return (
            db.update_task(
                task_id,
                status="failed",
                failure_reason="artifact_publish_failed",
                logs=failed_logs,
                report=result["report"],
                scene=result["scene"],
                artifacts=[],
                updated_at=utc_now(),
            ),
            502,
        )
    return (
        db.update_task(
            task_id,
            status="completed",
            logs=completed_logs,
            report=result["report"],
            scene=result["scene"],
            artifacts=artifacts,
            failure_reason=None,
            updated_at=utc_now(),
        ),
        200,
    )


def run_photogrammetry_capture(
    task: dict[str, Any],
    settings: AppSettings,
    output_dir: Path,
    logs: list[str],
) -> PhotogrammetryResult:
    input_path = Path(task["input_path"])
    work_dir = output_dir / "reconstruction"
    images_dir = extract_capture_media(input_path, work_dir, settings, logs)
    capture_dir = work_dir / "capture"
    sparse_dir = work_dir / "sparse"
    dense_dir = work_dir / "dense"
    work_dir.mkdir(parents=True, exist_ok=True)
    sparse_dir.mkdir(parents=True, exist_ok=True)
    dense_dir.mkdir(parents=True, exist_ok=True)

    if not any(images_dir.iterdir()):
        report = {"valid": False, "source_kind": "capture", "capture_quality": {"valid": False, "issues": ["no_images_in_capture"]}}
        raise PipelineError("no_images_in_capture", [f"{utc_now()} no image files found in uploaded capture zip."], report=report)

    capture_quality = analyze_capture_quality(images_dir, capture_dir, settings)
    logs.append(
        f"{utc_now()} capture quality: valid={capture_quality['valid']} "
        f"usable={capture_quality['usable_frame_count']}/{capture_quality['frame_count']} "
        f"issues={','.join(capture_quality['issues']) or 'none'}"
    )
    if not capture_quality["valid"]:
        raise PipelineError(
            "capture_quality_failed",
            [f"{utc_now()} capture quality failed: {','.join(capture_quality['issues'])}"],
            report={"valid": False, "source_kind": "capture", "capture_quality": capture_quality},
        )

    provider = settings.reconstruction_provider
    if provider != "colmap":
        try:
            mesh_path = run_external_reconstruction_provider(
                provider=provider,
                task=task,
                settings=settings,
                images_dir=images_dir,
                capture_dir=capture_dir,
                work_dir=work_dir,
                logs=logs,
            )
            return PhotogrammetryResult(mesh_path=mesh_path, capture_quality=capture_quality)
        except ReconstructionProviderError as exc:
            raise PipelineError(
                exc.reason,
                exc.logs,
                report={"valid": False, "source_kind": "capture", "capture_quality": capture_quality},
            ) from exc

    missing = missing_tools(settings.photogrammetry_required_tools)
    if missing:
        raise PipelineError(
            "missing_reconstruction_dependencies",
            [f"{utc_now()} missing required reconstruction tool: {tool}" for tool in missing],
            report={"valid": False, "source_kind": "capture", "capture_quality": capture_quality},
        )

    database_path = work_dir / "colmap.db"
    commands = [
        ["colmap", "feature_extractor", "--database_path", str(database_path), "--image_path", str(images_dir)],
        ["colmap", "exhaustive_matcher", "--database_path", str(database_path)],
        [
            "colmap",
            "mapper",
            "--database_path",
            str(database_path),
            "--image_path",
            str(images_dir),
            "--output_path",
            str(sparse_dir),
        ],
        [
            "colmap",
            "image_undistorter",
            "--image_path",
            str(images_dir),
            "--input_path",
            str(sparse_dir / "0"),
            "--output_path",
            str(dense_dir),
            "--output_type",
            "COLMAP",
        ],
        ["InterfaceCOLMAP", "-i", str(dense_dir), "-o", str(work_dir / "scene.mvs")],
        ["DensifyPointCloud", str(work_dir / "scene.mvs"), "-o", str(work_dir / "scene_dense.mvs")],
        ["ReconstructMesh", str(work_dir / "scene_dense.mvs"), "-o", str(work_dir / "scene_mesh.mvs")],
        ["RefineMesh", str(work_dir / "scene_mesh.mvs"), "-o", str(work_dir / "scene_refine.mvs")],
        ["TextureMesh", str(work_dir / "scene_refine.mvs"), "-o", str(work_dir / "scene_textured.mvs")],
    ]

    for command in commands:
        logs.append(f"{utc_now()} running: {' '.join(command)}")
        result = subprocess.run(
            command,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=settings.command_timeout_seconds,
            check=False,
        )
        output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
        if output:
            logs.append(output[-4000:])
        if result.returncode != 0:
            raise PipelineError("reconstruction_failed", [f"{utc_now()} command failed with exit {result.returncode}"])

    candidates = sorted(work_dir.glob("*.obj")) + sorted(work_dir.rglob("*textured*.obj")) + sorted(work_dir.rglob("*mesh*.obj"))
    if not candidates:
        raise PipelineError("reconstruction_mesh_missing", [f"{utc_now()} reconstruction completed without an OBJ mesh output."])
    return PhotogrammetryResult(mesh_path=candidates[0], capture_quality=capture_quality)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def extract_capture_media(input_path: Path, work_dir: Path, settings: AppSettings, logs: list[str]) -> Path:
    images_dir = work_dir / "images"
    capture_dir = work_dir / "capture"
    if capture_dir.exists():
        shutil.rmtree(capture_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    capture_dir.mkdir(parents=True, exist_ok=True)

    if input_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(input_path) as archive:
            archive.extractall(capture_dir)
    elif input_path.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        target = capture_dir / input_path.name
        target.write_bytes(input_path.read_bytes())
    else:
        raise PipelineError("unsupported_capture_input", [f"{utc_now()} {input_path.name} is not a mesh, image/video, or capture zip."])

    frame_index = 1
    for candidate in sorted(capture_dir.rglob("*")):
        if candidate.suffix.lower() in IMAGE_EXTENSIONS:
            target = images_dir / f"frame_{frame_index:05d}{candidate.suffix.lower()}"
            target.write_bytes(candidate.read_bytes())
            frame_index += 1

    videos = sorted(candidate for candidate in capture_dir.rglob("*") if candidate.suffix.lower() in VIDEO_EXTENSIONS)
    if videos:
        if shutil.which("ffmpeg") is None:
            raise PipelineError("missing_video_dependency", [f"{utc_now()} missing required video extraction tool: ffmpeg"])
        for video in videos:
            pattern = images_dir / f"{video.stem}_%05d.jpg"
            command = ["ffmpeg", "-y", "-i", str(video), "-vf", "fps=2", "-q:v", "2", str(pattern)]
            logs.append(f"{utc_now()} running: {' '.join(command)}")
            result = subprocess.run(
                command,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=settings.command_timeout_seconds,
                check=False,
            )
            output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
            if output:
                logs.append(output[-4000:])
            if result.returncode != 0:
                raise PipelineError("video_frame_extraction_failed", [f"{utc_now()} ffmpeg failed with exit {result.returncode}"])

    return images_dir


def find_roomplan_json_in_capture(input_path: Path, work_dir: Path) -> dict[str, Any] | None:
    if input_path.suffix.lower() == ".json":
        return json.loads(input_path.read_text(encoding="utf-8"))
    if input_path.suffix.lower() != ".zip":
        return None
    extract_dir = work_dir / "roomplan_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    with zipfile.ZipFile(input_path) as archive:
        archive.extractall(extract_dir)
    candidates = sorted(
        candidate
        for candidate in extract_dir.rglob("*.json")
        if candidate.name.lower() in {"roomplan.json", "captured_room.json", "capturedroom.json"}
    )
    if not candidates:
        return None
    roomplan = json.loads(candidates[0].read_text(encoding="utf-8"))
    if isinstance(roomplan, dict):
        roomplan["_capture_root"] = str(extract_dir)
        roomplan["_source_json"] = str(candidates[0].relative_to(extract_dir))
    return roomplan


def find_rgbd_scene_with_error(input_path: Path, work_dir: Path, default_category: str) -> dict[str, Any] | None:
    try:
        return find_rgbd_scene_in_capture(input_path, work_dir, default_category)
    except RGBDLiftingError as exc:
        report = {"valid": False, "source_kind": "rgbd_lifting", "segmentation": {"valid": False, "reason": str(exc)}}
        raise PipelineError("rgbd_lifting_failed", [f"{utc_now()} RGB-D lifting failed: {exc}"], report=report) from exc


def find_scene_segmentation_with_error(
    *,
    input_path: Path,
    work_dir: Path,
    default_category: str,
    mode: str,
    settings: AppSettings,
    logs: list[str],
) -> dict[str, Any] | None:
    if mode != "scene":
        return None
    if mode == "scene" and settings.segmentation_provider == "sam2":
        try:
            return find_sam2_scene_in_capture(
                input_path=input_path,
                work_dir=work_dir,
                default_category=default_category,
                settings=settings,
                logs=logs,
                timestamp=utc_now(),
            )
        except SegmentationProviderError as exc:
            raise PipelineError(exc.reason, exc.logs, report=exc.report) from exc
    return find_rgbd_scene_with_error(input_path, work_dir, default_category)
