#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Real2Sim USD package in real Isaac Sim headless mode.")
    parser.add_argument("--package-dir")
    parser.add_argument("--usd-path")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        simulation_app_class = load_simulation_app_class()
        if args.check:
            print(json.dumps({"ok": True, "provider": "isaacsim", "mode": "check"}, ensure_ascii=False))
            return 0
        usd_path = resolve_usd_path(args)
        result = validate_usd_stage(simulation_app_class, usd_path, max(args.frames, 1), emit_before_close=True)
    except Exception as exc:
        print(json.dumps({"ok": False, "provider": "isaacsim", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    if result is not None:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


def load_simulation_app_class() -> type[Any]:
    try:
        from isaacsim import SimulationApp  # type: ignore

        return SimulationApp
    except Exception:
        pass
    try:
        from isaacsim.simulation_app import SimulationApp  # type: ignore

        return SimulationApp
    except Exception as exc:
        raise ImportError("isaacsim_simulation_app_required") from exc


def resolve_usd_path(args: argparse.Namespace) -> Path:
    if args.usd_path:
        usd_path = Path(args.usd_path)
    elif args.package_dir:
        usd_path = Path(args.package_dir) / "scene.usd"
    else:
        raise ValueError("--package-dir or --usd-path is required")
    usd_path = usd_path.resolve()
    if not usd_path.is_file():
        raise FileNotFoundError(str(usd_path))
    return usd_path


def validate_usd_stage(simulation_app_class: type[Any], usd_path: Path, frames: int, *, emit_before_close: bool = False) -> dict[str, Any] | None:
    simulation_app = simulation_app_class({"headless": True, "disable_viewport_updates": True})
    try:
        import omni.usd  # type: ignore

        context = omni.usd.get_context()
        opened = context.open_stage(str(usd_path))
        for _ in range(frames):
            simulation_app.update()
        stage = context.get_stage()
        if not opened or stage is None:
            raise RuntimeError("isaacsim_open_stage_failed")
        prim_count = sum(1 for _ in stage.Traverse())
        if prim_count <= 0:
            raise RuntimeError("isaacsim_stage_has_no_prims")
        result = {
            "ok": True,
            "provider": "isaacsim",
            "usd_path": str(usd_path),
            "frames": frames,
            "prim_count": prim_count,
        }
        if emit_before_close:
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return None
        return result
    finally:
        simulation_app.close()


if __name__ == "__main__":
    raise SystemExit(main())
