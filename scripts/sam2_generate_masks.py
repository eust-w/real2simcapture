#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate real SAM2 masks for an extracted Real2Sim capture.")
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--images-dir")
    parser.add_argument("--video-path")
    parser.add_argument("--output-masks-dir", required=True)
    parser.add_argument("--model-id", default=os.environ.get("REAL2SIM_SAM2_MODEL_ID", "facebook/sam2.1-hiera-tiny"))
    parser.add_argument("--checkpoint", default=os.environ.get("REAL2SIM_SAM2_CHECKPOINT"))
    parser.add_argument("--model-cfg", default=os.environ.get("REAL2SIM_SAM2_MODEL_CFG"))
    parser.add_argument("--device", default=os.environ.get("REAL2SIM_SAM2_DEVICE", "auto"))
    parser.add_argument("--max-masks", type=int, default=int(os.environ.get("REAL2SIM_SAM2_MAX_MASKS", "8")))
    parser.add_argument("--min-area", type=int, default=int(os.environ.get("REAL2SIM_SAM2_MIN_MASK_AREA", "64")))
    parser.add_argument("--points-per-side", type=int, default=int(os.environ.get("REAL2SIM_SAM2_POINTS_PER_SIDE", "16")))
    parser.add_argument("--check", action="store_true", help="Only verify imports and argument consistency.")
    args = parser.parse_args()

    try:
        if args.check:
            check_runtime(args)
            print(json.dumps({"ok": True, "provider": "sam2", "mode": "check"}, ensure_ascii=False))
            return 0
        result = generate_masks(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


def check_runtime(args: argparse.Namespace) -> None:
    import sam2  # noqa: F401
    import torch  # noqa: F401

    if bool(args.checkpoint) != bool(args.model_cfg):
        raise ValueError("checkpoint_and_model_cfg_must_be_provided_together")
    if args.checkpoint and not Path(args.checkpoint).is_file():
        raise FileNotFoundError(args.checkpoint)
    if args.model_cfg and not Path(args.model_cfg).is_file():
        raise FileNotFoundError(args.model_cfg)


def generate_masks(args: argparse.Namespace) -> dict[str, Any]:
    check_runtime(args)
    capture_dir = Path(args.capture_dir).resolve()
    output_dir = Path(args.output_masks_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    image_path = choose_image(capture_dir, Path(args.images_dir).resolve() if args.images_dir else None)
    temporary_dir: tempfile.TemporaryDirectory[str] | None = None
    if image_path is None:
        video_path = Path(args.video_path).resolve() if args.video_path else choose_video(capture_dir)
        if video_path is None:
            raise FileNotFoundError("no_image_or_video_input_found")
        temporary_dir = tempfile.TemporaryDirectory()
        image_path = Path(temporary_dir.name) / "video_frame_000001.png"
        extract_video_frame(video_path, image_path)

    image = np.asarray(Image.open(image_path).convert("RGB"))
    generator = build_mask_generator(args)
    masks = generator.generate(image)
    selected = select_masks(masks, args.max_masks, args.min_area)
    if not selected:
        raise RuntimeError("sam2_generated_no_masks")

    base_name = safe_stem(image_path.stem)
    output_paths: list[str] = []
    for index, mask in enumerate(selected, start=1):
        segmentation = np.asarray(mask["segmentation"], dtype=bool)
        mask_image = Image.fromarray((segmentation.astype(np.uint8) * 255), mode="L")
        output_path = output_dir / f"{base_name}_sam2_{index:03d}.png"
        mask_image.save(output_path)
        output_paths.append(str(output_path))

    if temporary_dir is not None:
        temporary_dir.cleanup()
    return {
        "ok": True,
        "provider": "sam2",
        "image": str(image_path),
        "mask_count": len(output_paths),
        "masks": output_paths,
        "model": args.checkpoint or args.model_id,
    }


def build_mask_generator(args: argparse.Namespace) -> Any:
    import torch
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator

    device = resolve_device(args.device, torch)
    generator_kwargs = {
        "points_per_side": args.points_per_side,
        "min_mask_region_area": args.min_area,
    }
    if args.checkpoint and args.model_cfg:
        from sam2.build_sam import build_sam2

        model = build_sam2(args.model_cfg, args.checkpoint, device=device)
        return SAM2AutomaticMaskGenerator(model, **generator_kwargs)
    return SAM2AutomaticMaskGenerator.from_pretrained(args.model_id, device=device, **generator_kwargs)


def resolve_device(value: str, torch_module: Any) -> str:
    if value != "auto":
        return value
    if torch_module.cuda.is_available():
        return "cuda"
    if getattr(torch_module.backends, "mps", None) is not None and torch_module.backends.mps.is_available():
        return "mps"
    return "cpu"


def choose_image(capture_dir: Path, images_dir: Path | None) -> Path | None:
    roots = [root for root in [images_dir, capture_dir / "images", capture_dir] if root and root.is_dir()]
    skipped_parts = {"masks", "depth", "lifted_meshes"}
    for root in roots:
        candidates = [
            path
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not skipped_parts.intersection(path.relative_to(root).parts)
        ]
        if candidates:
            return candidates[0]
    return None


def choose_video(capture_dir: Path) -> Path | None:
    return next((path for path in sorted(capture_dir.rglob("*")) if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS), None)


def extract_video_frame(video_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg_required_for_video_input")
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(video_path), "-frames:v", "1", str(output_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0 or not output_path.is_file():
        raise RuntimeError(f"ffmpeg_frame_extract_failed:{result.returncode}:{result.stderr[-1000:]}")


def select_masks(masks: list[dict[str, Any]], max_masks: int, min_area: int) -> list[dict[str, Any]]:
    filtered = [mask for mask in masks if int(mask.get("area") or np.asarray(mask.get("segmentation")).sum()) >= min_area]
    return sorted(filtered, key=lambda item: (float(item.get("predicted_iou") or 0.0), int(item.get("area") or 0)), reverse=True)[:max_masks]


def safe_stem(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in value.strip()).strip("_").lower()
    return cleaned or "sam2_mask"


if __name__ == "__main__":
    raise SystemExit(main())
