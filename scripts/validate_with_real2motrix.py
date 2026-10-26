#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Real2Sim export through the local Real2Motrix package validator.")
    parser.add_argument("--package-dir", required=True)
    parser.add_argument("--real2motrix-dir", default=os.environ.get("REAL2MOTRIX_DIR"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.real2motrix_dir:
        parser.error("set REAL2MOTRIX_DIR or pass --real2motrix-dir")

    try:
        validate_package = load_real2motrix_validator(Path(args.real2motrix_dir))
        if args.check:
            print(json.dumps({"ok": True, "provider": "motrixsim", "mode": "check"}, ensure_ascii=False))
            return 0
        report = validate_real2sim_package(Path(args.package_dir), validate_package)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("valid") else 1


def load_real2motrix_validator(real2motrix_dir: Path):
    backend = real2motrix_dir / "backend"
    if not backend.is_dir():
        raise FileNotFoundError(f"Real2Motrix backend not found: {backend}")
    sys.path.insert(0, str(backend))
    module = importlib.import_module("app.pipeline.motrix.validate")
    return module.validate_package


def validate_real2sim_package(package_dir: Path, validate_package) -> dict[str, Any]:
    package_dir = package_dir.resolve()
    scene = read_json(package_dir / "scene.json")
    manifest = read_json(package_dir / "manifest.json")
    with tempfile.TemporaryDirectory(prefix="real2sim_motrix_") as tmp:
        motrix_dir = Path(tmp) / "motrix_scene"
        materialize_motrix_scene(package_dir, scene, manifest, motrix_dir)
        report = validate_package(motrix_dir)
        report["adapter"] = {
            "provider": "real2motrix",
            "source_package_dir": str(package_dir),
            "object_count": len(scene.get("objects", [])),
            "static_geometry_count": len(scene.get("static_geometry", [])),
        }
        return report


def materialize_motrix_scene(package_dir: Path, scene: dict[str, Any], manifest: dict[str, Any], motrix_dir: Path) -> None:
    mesh_dir = motrix_dir / "meshes"
    metadata_dir = motrix_dir / "metadata"
    object_root = mesh_dir / "objects"
    object_root.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)

    visual_meshes = []
    collision_meshes = []
    object_manifests = []
    for entry in [*scene.get("static_geometry", []), *scene.get("objects", [])]:
        visual_mesh = load_entry_mesh(package_dir, entry.get("visual_mesh"))
        collision_mesh = load_entry_mesh(package_dir, entry.get("collision_mesh"))
        if visual_mesh is not None:
            visual_meshes.append(visual_mesh)
        if collision_mesh is not None:
            collision_meshes.append(collision_mesh)
        if entry in scene.get("objects", []):
            object_id = slugify(str(entry.get("id") or entry.get("name") or f"object_{len(object_manifests) + 1:03d}"))
            object_dir = object_root / object_id
            object_dir.mkdir(parents=True)
            object_visual_path = object_dir / "visual.obj"
            object_collision_path = object_dir / "collision.obj"
            (visual_mesh or fallback_box(entry)).export(object_visual_path)
            (collision_mesh or fallback_box(entry)).export(object_collision_path)
            object_manifests.append(
                {
                    "id": object_id,
                    "label": entry.get("name") or object_id,
                    "category": entry.get("category"),
                    "visual_mesh": f"meshes/objects/{object_id}/visual.obj",
                    "collision_mesh": f"meshes/objects/{object_id}/collision.obj",
                }
            )

    scene_visual = concatenate_or_box(visual_meshes)
    scene_collision = concatenate_or_box(collision_meshes)
    align_min_z(scene_visual)
    align_min_z(scene_collision)
    scene_visual.export(mesh_dir / "scene_visual.obj")
    scene_collision.export(mesh_dir / "scene_collision.obj")

    asset_manifest = {
        "type": "motrix_scene_package",
        "unit": manifest.get("unit", scene.get("unit", "meter")),
        "coordinate_system": "motrix_world",
        "scene": {
            "visual_mesh": "meshes/scene_visual.obj",
            "collision_mesh": "meshes/scene_collision.obj",
            "source": "real2sim_adapter",
        },
        "objects": object_manifests,
    }
    (metadata_dir / "asset_manifest.json").write_text(json.dumps(asset_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (metadata_dir / "scene_manifest.json").write_text(json.dumps(asset_manifest["scene"], indent=2, ensure_ascii=False), encoding="utf-8")
    (metadata_dir / "object_manifest.json").write_text(json.dumps({"objects": object_manifests}, indent=2, ensure_ascii=False), encoding="utf-8")
    (motrix_dir / "scene.xml").write_text(render_motrix_mjcf(object_manifests), encoding="utf-8")
    (motrix_dir / "scene.urdf").write_text(render_motrix_urdf(object_manifests), encoding="utf-8")
    (motrix_dir / "scene.json").write_text(
        json.dumps(
            {
                "name": "real2sim_motrix_scene",
                "type": "motrix_scene_package",
                "entry": "scene.xml",
                "entries": {"mjcf": "scene.xml", "urdf": "scene.urdf"},
                "assets": {"visual_mesh": "meshes/scene_visual.obj", "collision_mesh": "meshes/scene_collision.obj"},
                "metadata": "metadata/asset_manifest.json",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def load_entry_mesh(package_dir: Path, reference: Any) -> trimesh.Trimesh | None:
    if not isinstance(reference, str) or not reference:
        return None
    path = package_dir / reference
    if not path.is_file():
        return None
    loaded = trimesh.load(path, force="mesh")
    if isinstance(loaded, trimesh.Trimesh) and len(loaded.faces) > 0:
        return loaded
    return None


def fallback_box(entry: dict[str, Any]) -> trimesh.Trimesh:
    dimensions = entry.get("dimensions") if isinstance(entry.get("dimensions"), list) else [0.1, 0.1, 0.1]
    return trimesh.creation.box(extents=np.maximum(np.array(dimensions[:3], dtype=float), [0.001, 0.001, 0.001]))


def concatenate_or_box(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    usable = [mesh for mesh in meshes if isinstance(mesh, trimesh.Trimesh) and len(mesh.faces) > 0]
    if not usable:
        return trimesh.creation.box(extents=[0.1, 0.1, 0.1])
    if len(usable) == 1:
        return usable[0].copy()
    return trimesh.util.concatenate([mesh.copy() for mesh in usable])


def align_min_z(mesh: trimesh.Trimesh) -> None:
    bounds = mesh.bounds
    if np.all(np.isfinite(bounds)):
        mesh.apply_translation([0.0, 0.0, -float(bounds[0][2])])


def render_motrix_mjcf(objects: list[dict[str, Any]]) -> str:
    asset_lines = [
        '    <mesh name="scene_visual" file="scene_visual.obj"/>',
        '    <mesh name="scene_collision" file="scene_collision.obj"/>',
    ]
    body_lines = [
        '    <body name="static_scene" pos="0 0 0">',
        '      <geom name="scene_collision_geom" type="mesh" mesh="scene_collision"/>',
        '      <geom name="scene_visual_geom" type="mesh" mesh="scene_visual" contype="0" conaffinity="0"/>',
        "    </body>",
    ]
    for obj in objects:
        object_id = obj["id"]
        asset_lines.append(f'    <mesh name="{object_id}_visual" file="objects/{object_id}/visual.obj"/>')
        asset_lines.append(f'    <mesh name="{object_id}_collision" file="objects/{object_id}/collision.obj"/>')
        body_lines.extend(
            [
                f'    <body name="{object_id}" pos="0 0 0">',
                f'      <geom name="{object_id}_collision_geom" type="mesh" mesh="{object_id}_collision"/>',
                f'      <geom name="{object_id}_visual_geom" type="mesh" mesh="{object_id}_visual" contype="0" conaffinity="0"/>',
                "    </body>",
            ]
        )
    return "\n".join(
        [
            '<mujoco model="real2sim_motrix_scene">',
            '  <compiler angle="radian" meshdir="meshes"/>',
            "  <asset>",
            *asset_lines,
            "  </asset>",
            "  <worldbody>",
            *body_lines,
            "  </worldbody>",
            "</mujoco>",
            "",
        ]
    )


def render_motrix_urdf(objects: list[dict[str, Any]]) -> str:
    links = [
        '  <link name="static_scene"><visual><geometry><mesh filename="meshes/scene_visual.obj"/></geometry></visual><collision><geometry><mesh filename="meshes/scene_collision.obj"/></geometry></collision></link>'
    ]
    for obj in objects:
        object_id = obj["id"]
        links.append(
            f'  <link name="{object_id}"><visual><geometry><mesh filename="meshes/objects/{object_id}/visual.obj"/></geometry></visual><collision><geometry><mesh filename="meshes/objects/{object_id}/collision.obj"/></geometry></collision></link>'
        )
    return "\n".join(['<?xml version="1.0"?>', '<robot name="real2sim_motrix_scene">', *links, "</robot>", ""])


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value.strip()).strip("_")
    return cleaned or "object"


if __name__ == "__main__":
    raise SystemExit(main())
