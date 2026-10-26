from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def analyze_capture_quality(images_dir: Path, capture_dir: Path, settings: Any) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    for image_path in sorted(path for path in images_dir.rglob("*") if path.is_file()):
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".heic"}:
            continue
        frames.append(analyze_image_frame(image_path, settings))

    usable_frames = [frame for frame in frames if frame.get("usable")]
    blurry = [frame for frame in frames if frame.get("blur_status") == "blurry"]
    underexposed = [frame for frame in frames if frame.get("exposure_status") == "underexposed"]
    overexposed = [frame for frame in frames if frame.get("exposure_status") == "overexposed"]
    unreadable = [frame for frame in frames if frame.get("read_error")]
    metadata = analyze_capture_metadata(capture_dir)

    issues: list[str] = []
    if len(frames) < settings.capture_min_frames:
        issues.append("too_few_frames")
    if len(usable_frames) < settings.capture_min_usable_frames:
        issues.append("too_few_usable_frames")
    if unreadable:
        issues.append("unreadable_frames")
    if frames and len(blurry) == len(frames):
        issues.append("all_frames_blurry")
    if frames and len(underexposed) + len(overexposed) == len(frames):
        issues.append("all_frames_bad_exposure")
    if metadata["coverage_angle_degrees"] is not None and metadata["coverage_angle_degrees"] < settings.capture_min_coverage_degrees:
        issues.append("insufficient_pose_coverage")
    if settings.capture_require_scale_reference and not metadata["has_scale_reference"]:
        issues.append("missing_scale_reference")

    return {
        "valid": not issues,
        "issues": issues,
        "frame_count": len(frames),
        "usable_frame_count": len(usable_frames),
        "blurry_frame_count": len(blurry),
        "underexposed_frame_count": len(underexposed),
        "overexposed_frame_count": len(overexposed),
        "unreadable_frame_count": len(unreadable),
        "has_scale_reference": metadata["has_scale_reference"],
        "coverage_angle_degrees": metadata["coverage_angle_degrees"],
        "tracking_lost_events": metadata["tracking_lost_events"],
        "thresholds": {
            "min_frames": settings.capture_min_frames,
            "min_usable_frames": settings.capture_min_usable_frames,
            "blur_variance": settings.capture_blur_variance_threshold,
            "min_exposure_mean": settings.capture_min_exposure_mean,
            "max_exposure_mean": settings.capture_max_exposure_mean,
            "max_clipped_ratio": settings.capture_max_clipped_ratio,
            "min_coverage_degrees": settings.capture_min_coverage_degrees,
            "require_scale_reference": settings.capture_require_scale_reference,
        },
        "frames": frames,
    }


def analyze_image_frame(image_path: Path, settings: Any) -> dict[str, Any]:
    try:
        with Image.open(image_path) as image:
            gray = np.asarray(image.convert("L"), dtype=np.float32)
    except Exception as exc:
        return {
            "path": image_path.name,
            "usable": False,
            "read_error": str(exc),
            "blur_score": None,
            "exposure_mean": None,
            "dark_clip_ratio": None,
            "bright_clip_ratio": None,
            "blur_status": "unreadable",
            "exposure_status": "unreadable",
        }

    blur_score = laplacian_variance(gray)
    exposure_mean = float(gray.mean())
    dark_clip_ratio = float((gray <= 5).mean())
    bright_clip_ratio = float((gray >= 250).mean())
    blur_status = "sharp" if blur_score >= settings.capture_blur_variance_threshold else "blurry"
    if exposure_mean < settings.capture_min_exposure_mean or dark_clip_ratio > settings.capture_max_clipped_ratio:
        exposure_status = "underexposed"
    elif exposure_mean > settings.capture_max_exposure_mean or bright_clip_ratio > settings.capture_max_clipped_ratio:
        exposure_status = "overexposed"
    else:
        exposure_status = "balanced"
    usable = blur_status == "sharp" and exposure_status == "balanced"
    return {
        "path": image_path.name,
        "usable": usable,
        "read_error": None,
        "width": int(gray.shape[1]),
        "height": int(gray.shape[0]),
        "blur_score": blur_score,
        "exposure_mean": exposure_mean,
        "dark_clip_ratio": dark_clip_ratio,
        "bright_clip_ratio": bright_clip_ratio,
        "blur_status": blur_status,
        "exposure_status": exposure_status,
    }


def laplacian_variance(gray: np.ndarray) -> float:
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    center = gray[1:-1, 1:-1]
    laplacian = -4.0 * center + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    return float(laplacian.var())


def analyze_capture_metadata(capture_dir: Path) -> dict[str, Any]:
    metadata_values: list[Any] = []
    for json_path in sorted(capture_dir.rglob("*.json")):
        try:
            metadata_values.append(json.loads(json_path.read_text(encoding="utf-8")))
        except Exception:
            continue
    has_scale = any(has_scale_reference(value) for value in metadata_values)
    positions = [position for value in metadata_values for position in collect_positions(value)]
    return {
        "has_scale_reference": has_scale,
        "coverage_angle_degrees": estimate_coverage_angle(positions) if len(positions) >= 2 else None,
        "tracking_lost_events": sum(count_tracking_lost(value) for value in metadata_values),
    }


def has_scale_reference(value: Any) -> bool:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        if {"marker_length_m", "scale_meters_per_unit", "scale_reference_m", "lidar_scale", "unit"}.intersection(keys):
            return True
        return any(has_scale_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(has_scale_reference(child) for child in value)
    return False


def collect_positions(value: Any) -> list[list[float]]:
    positions: list[list[float]] = []
    if isinstance(value, dict):
        candidate = value.get("position") or value.get("camera_position") or value.get("translation")
        if is_vector3(candidate):
            positions.append([float(candidate[0]), float(candidate[1]), float(candidate[2])])
        for child in value.values():
            positions.extend(collect_positions(child))
    elif isinstance(value, list):
        for child in value:
            positions.extend(collect_positions(child))
    return positions


def is_vector3(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 3 and all(isinstance(item, int | float) for item in value[:3])


def count_tracking_lost(value: Any) -> int:
    if isinstance(value, dict):
        count = 0
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"tracking_state", "trackingstate"} and str(child).lower() not in {"normal", "mapped", "tracking"}:
                count += 1
            elif lowered in {"tracking_lost", "trackinglost"} and child is True:
                count += 1
            count += count_tracking_lost(child)
        return count
    if isinstance(value, list):
        return sum(count_tracking_lost(child) for child in value)
    return 0


def estimate_coverage_angle(positions: list[list[float]]) -> float | None:
    points = np.array(positions, dtype=float)
    if points.shape[0] < 2:
        return None
    center = points[:, :2].mean(axis=0)
    offsets = points[:, :2] - center
    angles = sorted(math.atan2(float(offset[1]), float(offset[0])) for offset in offsets if np.linalg.norm(offset) > 1e-6)
    if len(angles) < 2:
        return None
    wrapped = angles + [angles[0] + 2.0 * math.pi]
    max_gap = max(wrapped[index + 1] - wrapped[index] for index in range(len(angles)))
    coverage = max(0.0, 2.0 * math.pi - max_gap)
    return float(math.degrees(coverage))
