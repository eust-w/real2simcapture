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


ROOT = Path(__file__).resolve().parents[1]
SWIFT_SOURCE = ROOT / "scripts" / "apple_object_capture_cli.swift"
SWIFT_BINARY = ROOT / ".build" / "real2sim" / "apple_object_capture_cli"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Apple RealityKit Object Capture and export an OBJ mesh.")
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-mesh", required=True)
    parser.add_argument("--detail", default=os.environ.get("REAL2SIM_APPLE_OBJECT_CAPTURE_DETAIL", "medium"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        compile_swift_cli()
        check_blender_usd_support()
        if args.check:
            print(json.dumps({"ok": True, "provider": "apple_object_capture", "mode": "check"}, ensure_ascii=False))
            return 0
        result = run_capture(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


def compile_swift_cli() -> None:
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise FileNotFoundError("swiftc_required")
    SWIFT_BINARY.parent.mkdir(parents=True, exist_ok=True)
    if SWIFT_BINARY.is_file() and SWIFT_BINARY.stat().st_mtime >= SWIFT_SOURCE.stat().st_mtime:
        return
    result = subprocess.run(
        [swiftc, "-parse-as-library", str(SWIFT_SOURCE), "-O", "-o", str(SWIFT_BINARY)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"swift_compile_failed:{result.returncode}:{combined_output(result)[-2000:]}")


def check_blender_usd_support() -> None:
    blender = shutil.which("blender")
    if not blender:
        raise FileNotFoundError("blender_required_for_usdz_to_obj_conversion")
    script = "import bpy; raise SystemExit(0 if hasattr(bpy.ops.wm, 'usd_import') and (hasattr(bpy.ops.wm, 'obj_export') or hasattr(bpy.ops.export_scene, 'obj')) else 1)"
    result = subprocess.run([blender, "--background", "--python-expr", script], capture_output=True, text=True, timeout=60, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"blender_usd_or_obj_operator_missing:{combined_output(result)[-2000:]}")


def run_capture(args: argparse.Namespace) -> dict[str, str | bool]:
    images_dir = Path(args.images_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_mesh = Path(args.output_mesh).resolve()
    if not images_dir.is_dir():
        raise FileNotFoundError(str(images_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_mesh.parent.mkdir(parents=True, exist_ok=True)
    output_usdz = output_dir / "apple_object_capture.usdz"

    result = subprocess.run(
        [
            str(SWIFT_BINARY),
            "--images-dir",
            str(images_dir),
            "--output-usdz",
            str(output_usdz),
            "--detail",
            str(args.detail),
        ],
        capture_output=True,
        text=True,
        timeout=None,
        check=False,
    )
    if result.returncode != 0 or not output_usdz.is_file():
        raise RuntimeError(f"apple_object_capture_failed:{result.returncode}:{combined_output(result)[-4000:]}")
    if output_mesh.suffix.lower() == ".usdz":
        shutil.copy2(output_usdz, output_mesh)
    else:
        convert_usdz_to_obj(output_usdz, output_mesh)
    if not output_mesh.is_file() or output_mesh.stat().st_size == 0:
        raise RuntimeError("apple_object_capture_output_mesh_missing")
    return {"ok": True, "provider": "apple_object_capture", "output_usdz": str(output_usdz), "output_mesh": str(output_mesh)}


def convert_usdz_to_obj(input_usdz: Path, output_obj: Path) -> None:
    blender = shutil.which("blender")
    if not blender:
        raise FileNotFoundError("blender_required_for_usdz_to_obj_conversion")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        script_path = Path(handle.name)
        handle.write(
            "\n".join(
                [
                    "import bpy",
                    "bpy.ops.object.select_all(action='SELECT')",
                    "bpy.ops.object.delete()",
                    f"bpy.ops.wm.usd_import(filepath={str(input_usdz)!r})",
                    "objects = [obj for obj in bpy.context.scene.objects if getattr(obj, 'type', None) == 'MESH']",
                    "if not objects:",
                    "    raise SystemExit('no_mesh_objects_imported_from_usdz')",
                    f"output_path = {str(output_obj)!r}",
                    "if hasattr(bpy.ops.wm, 'obj_export'):",
                    "    bpy.ops.wm.obj_export(filepath=output_path)",
                    "else:",
                    "    bpy.ops.export_scene.obj(filepath=output_path)",
                ]
            )
        )
    try:
        result = subprocess.run([blender, "--background", "--python", str(script_path)], capture_output=True, text=True, timeout=300, check=False)
    finally:
        script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"blender_usdz_to_obj_failed:{result.returncode}:{combined_output(result)[-4000:]}")


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())


if __name__ == "__main__":
    raise SystemExit(main())
