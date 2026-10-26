from __future__ import annotations

import shutil
import shlex
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from .rgbd_lifting import RGBDLiftingError, lift_rgbd_scene
from .settings import AppSettings


class SegmentationProviderError(Exception):
    def __init__(self, reason: str, logs: list[str], report: dict[str, Any] | None = None):
        self.reason = reason
        self.logs = logs
        self.report = report
        super().__init__(reason)


def segmentation_health(settings: AppSettings) -> dict[str, Any]:
    providers = {
        "rgbd_masks": {
            "available": True,
            "reason": None,
            "requires": [
                "intrinsics.json",
                "depth/*.npy|png",
                "optional masks/*.png for object-specific lifting",
                "optional poses.json",
            ],
        },
        "sam2": sam2_health(settings),
    }
    return {"provider": settings.segmentation_provider, "providers": providers}


def sam2_health(settings: AppSettings) -> dict[str, Any]:
    command = settings.sam2_command
    if not command:
        return {"available": False, "reason": "sam2_command_required"}
    try:
        executable = shlex.split(command)[0]
    except ValueError as exc:
        return {"available": False, "reason": f"invalid_command: {exc}", "command": None}
    if Path(executable).is_file() or shutil.which(executable):
        return {"available": True, "reason": None, "command": executable}
    return {"available": False, "reason": "sam2_command_not_found", "command": executable}


def find_sam2_scene_in_capture(
    *,
    input_path: Path,
    work_dir: Path,
    default_category: str,
    settings: AppSettings,
    logs: list[str],
    timestamp: str,
) -> dict[str, Any] | None:
    if input_path.suffix.lower() != ".zip":
        return None
    if not settings.sam2_command:
        raise SegmentationProviderError(
            "sam2_command_required",
            [f"{timestamp} SAM2 segmentation provider selected but REAL2SIM_SAM2_COMMAND is not configured."],
            report={"valid": False, "source_kind": "rgbd_lifting", "segmentation": {"valid": False, "provider": "sam2", "reason": "sam2_command_required"}},
        )

    extract_dir = work_dir / "sam2_segmentation_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    with zipfile.ZipFile(input_path) as archive:
        archive.extractall(extract_dir)

    masks_dir = extract_dir / "masks"
    masks_dir.mkdir(exist_ok=True)
    run_sam2_command(settings, extract_dir, masks_dir, logs, timestamp)
    mask_paths = sorted(path for path in masks_dir.glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg"})
    if not mask_paths:
        raise SegmentationProviderError(
            "sam2_masks_missing",
            [f"{timestamp} SAM2 command completed but did not create mask images in {masks_dir}."],
            report={"valid": False, "source_kind": "rgbd_lifting", "segmentation": {"valid": False, "provider": "sam2", "reason": "sam2_masks_missing"}},
        )

    try:
        scene = lift_rgbd_scene(extract_dir, mask_paths, default_category)
    except RGBDLiftingError as exc:
        raise SegmentationProviderError(
            "rgbd_lifting_failed",
            [f"{timestamp} SAM2 masks could not be lifted into 3D: {exc}"],
            report={"valid": False, "source_kind": "rgbd_lifting", "segmentation": {"valid": False, "provider": "sam2", "reason": str(exc)}},
        ) from exc
    scene.setdefault("segmentation", {})
    scene["segmentation"] = {
        **scene["segmentation"],
        "provider": "sam2",
        "valid": True,
        "output_masks_dir": str(masks_dir),
    }
    logs.append(f"{timestamp} SAM2 segmentation generated {len(mask_paths)} mask image(s).")
    return scene


def run_sam2_command(settings: AppSettings, capture_dir: Path, masks_dir: Path, logs: list[str], timestamp: str) -> None:
    context = {
        "capture_dir": str(capture_dir),
        "images_dir": str(capture_dir / "images"),
        "video_path": str(first_existing(capture_dir, {".mp4", ".mov", ".m4v"}) or ""),
        "depth_dir": str(capture_dir / "depth"),
        "intrinsics_path": str(capture_dir / "intrinsics.json"),
        "poses_path": str(capture_dir / "poses.json"),
        "objects_path": str(capture_dir / "objects.json"),
        "surfaces_path": str(capture_dir / "surfaces.json"),
        "output_masks_dir": str(masks_dir),
    }
    try:
        command = settings.sam2_command.format(**context) if settings.sam2_command else ""
        argv = shlex.split(command)
    except (KeyError, ValueError) as exc:
        raise SegmentationProviderError(
            "sam2_command_invalid",
            [f"{timestamp} invalid SAM2 command template: {exc}"],
            report={"valid": False, "source_kind": "rgbd_lifting", "segmentation": {"valid": False, "provider": "sam2", "reason": "sam2_command_invalid"}},
        ) from exc
    executable = Path(argv[0])
    if not executable.is_file() and shutil.which(argv[0]) is None:
        raise SegmentationProviderError(
            "sam2_command_not_found",
            [f"{timestamp} SAM2 executable not found: {argv[0]}"],
            report={"valid": False, "source_kind": "rgbd_lifting", "segmentation": {"valid": False, "provider": "sam2", "reason": "sam2_command_not_found"}},
        )

    logs.append(f"{timestamp} running SAM2 segmentation command: {' '.join(argv)}")
    result = subprocess.run(
        argv,
        cwd=capture_dir,
        capture_output=True,
        text=True,
        timeout=settings.command_timeout_seconds,
        check=False,
    )
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    if output:
        logs.append(output[-4000:])
    if result.returncode != 0:
        raise SegmentationProviderError(
            "sam2_segmentation_failed",
            [f"{timestamp} SAM2 command failed with exit {result.returncode}."],
            report={"valid": False, "source_kind": "rgbd_lifting", "segmentation": {"valid": False, "provider": "sam2", "reason": "sam2_segmentation_failed"}},
        )


def first_existing(root: Path, suffixes: set[str]) -> Path | None:
    return next((candidate for candidate in sorted(root.rglob("*")) if candidate.is_file() and candidate.suffix.lower() in suffixes), None)
