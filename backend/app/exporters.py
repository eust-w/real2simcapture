from __future__ import annotations

import copy
import json
import math
import re
import shlex
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .materials import resolve_material_metadata

MESH_EXTENSIONS = {".obj", ".glb", ".gltf", ".ply", ".stl"}
RESIDUAL_SCENE_MESH_STEMS = {"scene_mesh", "arkit_mesh", "room_mesh", "residual_scene", "residual_mesh", "world_mesh"}
TEXTURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tga", ".bmp", ".tif", ".tiff"}
MTL_TEXTURE_KEYS = {"bump", "decal", "disp", "map_bump", "map_d", "map_ka", "map_kd", "map_ke", "map_ks", "map_ns", "norm", "refl"}


@dataclass(frozen=True)
class CollisionAssets:
    combined_mesh: trimesh.Trimesh
    parts: list[trimesh.Trimesh]
    backend: str
    reason: str | None = None


@dataclass(frozen=True)
class MeshCleanupResult:
    mesh: trimesh.Trimesh
    report: dict[str, Any]


def slugify(value: str, fallback: str = "asset") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower()
    return slug or fallback


def artifact_url(base_url: str, task_id: str, path: str) -> str:
    return f"/api/artifacts/{task_id}/{path}"


def load_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force=None)
    if isinstance(loaded, trimesh.Scene):
        meshes = [geometry for geometry in loaded.geometry.values() if isinstance(geometry, trimesh.Trimesh)]
        if not meshes:
            raise ValueError("No mesh geometry found in uploaded scene.")
        return trimesh.util.concatenate(meshes)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError("Uploaded file did not contain a supported mesh.")
    if loaded.faces is None or len(loaded.faces) == 0:
        raise ValueError("Uploaded mesh has no faces.")
    return loaded


def make_collision_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    try:
        hull = mesh.convex_hull
        if isinstance(hull, trimesh.Trimesh) and len(hull.faces) > 0 and abs(float(hull.volume)) > 1e-12:
            return hull
    except Exception:
        pass

    return bounds_collision_mesh(mesh)


def bounds_collision_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    bounds = mesh.bounds
    extents = np.maximum(bounds[1] - bounds[0], np.array([0.001, 0.001, 0.001]))
    transform = np.eye(4)
    transform[:3, 3] = mesh.bounding_box.centroid
    return trimesh.creation.box(extents=extents, transform=transform)


def cleanup_mesh_for_export(mesh: trimesh.Trimesh, floater_area_ratio_threshold: float = 0.005) -> MeshCleanupResult:
    working = mesh.copy()
    faces_before = int(len(working.faces))
    vertices_before = int(len(working.vertices))
    area_before = float(working.area) if math.isfinite(float(working.area)) else 0.0

    try:
        valid_faces = np.isfinite(working.area_faces) & (working.area_faces > 1e-12)
        if len(valid_faces) == len(working.faces) and not bool(np.all(valid_faces)):
            working.update_faces(valid_faces)
        working.remove_unreferenced_vertices()
    except Exception:
        pass

    components = [component for component in working.split(only_watertight=False) if len(component.faces) > 0]
    components_before = len(components) if components else (1 if len(working.faces) else 0)
    removed_components: list[trimesh.Trimesh] = []
    kept_components: list[trimesh.Trimesh] = []
    if len(components) > 1:
        largest_area = max(float(component.area) for component in components)
        min_area = largest_area * floater_area_ratio_threshold
        for component in components:
            if float(component.area) >= min_area:
                kept_components.append(component)
            else:
                removed_components.append(component)
        if kept_components:
            working = trimesh.util.concatenate(kept_components)
    elif components:
        kept_components = components
        working = components[0]

    holes_filled = False
    normals_fixed = False
    try:
        trimesh.repair.fix_normals(working, multibody=True)
        normals_fixed = True
    except Exception:
        pass
    try:
        holes_filled = bool(trimesh.repair.fill_holes(working))
    except Exception:
        holes_filled = False
    try:
        working.remove_unreferenced_vertices()
    except Exception:
        pass

    report = {
        "enabled": True,
        "floater_area_ratio_threshold": floater_area_ratio_threshold,
        "vertices_before": vertices_before,
        "faces_before": faces_before,
        "area_before": area_before,
        "vertices_after": int(len(working.vertices)),
        "faces_after": int(len(working.faces)),
        "area_after": float(working.area) if math.isfinite(float(working.area)) else 0.0,
        "components_before": components_before,
        "components_after": len(kept_components) if kept_components else (1 if len(working.faces) else 0),
        "removed_component_count": len(removed_components),
        "removed_face_count": int(sum(len(component.faces) for component in removed_components)),
        "removed_area": float(sum(float(component.area) for component in removed_components)),
        "normals_fixed": normals_fixed,
        "holes_filled": holes_filled,
    }
    return MeshCleanupResult(mesh=working, report=report)


def make_collision_assets(mesh: trimesh.Trimesh) -> CollisionAssets:
    try:
        import coacd  # type: ignore

        coacd.set_log_level("error")
        coacd_mesh = coacd.Mesh(np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces, dtype=np.int32))
        decomposed = coacd.run_coacd(
            coacd_mesh,
            threshold=0.05,
            max_convex_hull=16,
            preprocess_resolution=40,
            resolution=2000,
            mcts_nodes=20,
            mcts_iterations=80,
            merge=True,
            max_ch_vertex=256,
            seed=0,
        )
        parts = [
            trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float), faces=np.asarray(faces, dtype=np.int64), process=True)
            for vertices, faces in decomposed
        ]
        parts = [part for part in parts if len(part.vertices) > 0 and len(part.faces) > 0]
        if parts:
            return CollisionAssets(combined_mesh=trimesh.util.concatenate(parts), parts=parts, backend="coacd")
    except Exception as exc:
        fallback = make_collision_mesh(mesh)
        return CollisionAssets(combined_mesh=fallback, parts=[fallback], backend="convex_hull", reason=f"coacd_failed:{type(exc).__name__}:{exc}")

    fallback = make_collision_mesh(mesh)
    return CollisionAssets(combined_mesh=fallback, parts=[fallback], backend="convex_hull", reason="coacd_returned_no_parts")


def export_collision_assets(collision_assets: CollisionAssets, assets_dir: Path, asset_slug: str) -> tuple[Path, list[str]]:
    collision_obj = assets_dir / f"{asset_slug}_collision.obj"
    collision_assets.combined_mesh.export(collision_obj)
    if len(collision_assets.parts) == 1:
        return collision_obj, [f"assets/{collision_obj.name}"]
    collision_paths: list[str] = []
    for index, part in enumerate(collision_assets.parts, start=1):
        part_path = assets_dir / f"{asset_slug}_collision_part_{index:03d}.obj"
        part.export(part_path)
        collision_paths.append(f"assets/{part_path.name}")
    return collision_obj, collision_paths


def mesh_metrics(mesh: trimesh.Trimesh, collision_assets: CollisionAssets) -> dict[str, Any]:
    collision = collision_assets.combined_mesh
    bounds = mesh.bounds
    extents = bounds[1] - bounds[0]
    return {
        "visual_vertices": int(len(mesh.vertices)),
        "visual_faces": int(len(mesh.faces)),
        "collision_vertices": int(len(collision.vertices)),
        "collision_faces": int(len(collision.faces)),
        "collision_part_count": len(collision_assets.parts),
        "collision_backend": collision_assets.backend,
        "collision_fallback_reason": collision_assets.reason,
        "bounds_min": [float(v) for v in bounds[0]],
        "bounds_max": [float(v) for v in bounds[1]],
        "extents_m": [float(v) for v in extents],
        "watertight": bool(mesh.is_watertight),
        "volume_m3": float(abs(mesh.volume)) if math.isfinite(float(mesh.volume)) else 0.0,
    }


def estimate_mass(mesh: trimesh.Trimesh, provided_mass: float | None, density_kg_m3: float) -> tuple[float, str]:
    if provided_mass is not None and provided_mass > 0:
        return float(provided_mass), "provided"
    volume = float(abs(mesh.volume)) if math.isfinite(float(mesh.volume)) and abs(mesh.volume) > 0 else 0.0
    if volume == 0.0:
        bounds = mesh.bounds
        extents = np.maximum(bounds[1] - bounds[0], np.array([0.001, 0.001, 0.001]))
        volume = float(np.prod(extents))
    return float(volume * density_kg_m3), "estimated_from_volume"


def box_inertia(mass_kg: float, extents: list[float]) -> list[float]:
    x, y, z = [max(float(value), 0.001) for value in extents]
    return [
        mass_kg * (y * y + z * z) / 12.0,
        mass_kg * (x * x + z * z) / 12.0,
        mass_kg * (x * x + y * y) / 12.0,
    ]


def ensure_scene_material_metadata(scene: dict[str, Any]) -> None:
    for obj in scene.get("objects", []):
        obj.update(resolve_material_metadata(obj.get("category"), obj))
    for geometry in scene.get("static_geometry", []):
        geometry.update(resolve_material_metadata(geometry.get("category"), geometry))


def sync_report_physics_metadata(report: dict[str, Any], scene: dict[str, Any]) -> None:
    objects = scene.get("objects", [])
    if len(objects) != 1:
        return
    obj = objects[0]
    physics = report.setdefault("physics", {})
    for key in ["mass_kg", "friction", "inertia_diagonal", "material_category", "material_category_source"]:
        if key in obj:
            physics[key] = obj[key]


def create_box_mesh(dimensions: list[float], position: list[float] | None = None) -> trimesh.Trimesh:
    extents = np.maximum(np.array(dimensions, dtype=float), np.array([0.001, 0.001, 0.001]))
    transform = np.eye(4)
    if position is not None:
        transform[:3, 3] = np.array(position, dtype=float)
    return trimesh.creation.box(extents=extents, transform=transform)


def mesh_with_pose(mesh: trimesh.Trimesh, pose: dict[str, Any]) -> trimesh.Trimesh:
    positioned = mesh.copy()
    position = pose.get("position") if isinstance(pose, dict) else None
    if isinstance(position, list) and len(position) >= 3:
        transform = np.eye(4)
        transform[:3, 3] = np.array([float(position[0]), float(position[1]), float(position[2])], dtype=float)
        positioned.apply_transform(transform)
    return positioned


def source_surface_mesh_path(source: dict[str, Any], capture_root: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    absolute_value = source.get("surface_mesh_path")
    if isinstance(absolute_value, str) and absolute_value:
        candidates.append(Path(absolute_value))
    relative_value = source.get("surface_mesh")
    if isinstance(relative_value, str) and relative_value:
        relative_path = Path(relative_value)
        if relative_path.is_absolute():
            candidates.append(relative_path)
        if capture_root is not None:
            candidates.append(capture_root / relative_path)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file() or resolved.suffix.lower() not in MESH_EXTENSIONS:
            continue
        if capture_root is not None:
            try:
                resolved.relative_to(capture_root.resolve())
            except ValueError:
                continue
        return resolved
    return None


def has_surface_mesh_reference(source: dict[str, Any]) -> bool:
    return any(isinstance(source.get(key), str) and source.get(key) for key in ["surface_mesh", "surface_mesh_path"])


def entry_surface_source(entry: dict[str, Any]) -> dict[str, Any]:
    source = entry.get("source")
    if not isinstance(source, dict):
        return {}
    if has_surface_mesh_reference(source):
        return source
    capture = source.get("capture")
    if not isinstance(capture, dict):
        return {}
    if has_surface_mesh_reference(capture):
        return capture
    nested_capture = capture.get("capture")
    if isinstance(nested_capture, dict) and has_surface_mesh_reference(nested_capture):
        return nested_capture
    return {}


def load_source_surface_mesh(
    source: dict[str, Any],
    dimensions: list[float],
    capture_root: Path | None = None,
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    mesh_path = source_surface_mesh_path(source, capture_root)
    if mesh_path is None:
        return create_box_mesh(dimensions), {"visual_mesh_source": "parametric_box"}
    try:
        cleanup = cleanup_mesh_for_export(load_mesh(mesh_path))
    except Exception as exc:
        return create_box_mesh(dimensions), {"visual_mesh_source": "parametric_box", "surface_mesh_error": f"{type(exc).__name__}: {exc}"}
    return cleanup.mesh, {"visual_mesh_source": source.get("surface_mesh_source") or "capture_surface_mesh", "surface_mesh_path": str(mesh_path), "surface_mesh_cleanup": cleanup.report}


def extract_texture_assets(mesh_path: Path, mesh: trimesh.Trimesh, textures_dir: Path, asset_slug: str) -> list[str]:
    texture_paths: list[str] = []
    copied_sources: set[Path] = set()
    for source in find_external_texture_files(mesh_path):
        resolved = source.resolve()
        if resolved in copied_sources:
            continue
        copied_sources.add(resolved)
        target = unique_texture_path(textures_dir, asset_slug, source.name)
        shutil.copy2(source, target)
        texture_paths.append(f"textures/{target.name}")

    material = getattr(getattr(mesh, "visual", None), "material", None)
    image = getattr(material, "image", None)
    if image is not None and not texture_paths:
        target = unique_texture_path(textures_dir, asset_slug, "embedded_texture.png")
        image.save(target)
        texture_paths.append(f"textures/{target.name}")
    return texture_paths


def find_external_texture_files(mesh_path: Path) -> list[Path]:
    suffix = mesh_path.suffix.lower()
    if suffix == ".obj":
        return find_obj_texture_files(mesh_path)
    if suffix == ".gltf":
        return find_gltf_texture_files(mesh_path)
    return []


def find_obj_texture_files(obj_path: Path) -> list[Path]:
    if not obj_path.is_file():
        return []
    textures: list[Path] = []
    mtllibs: list[Path] = []
    for raw_line in obj_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.lower().startswith("mtllib "):
            continue
        for reference in split_material_references(line[len("mtllib ") :]):
            candidate = (obj_path.parent / reference).resolve()
            if candidate.is_file():
                mtllibs.append(candidate)

    for mtl_path in mtllibs:
        for reference in parse_mtl_texture_references(mtl_path):
            candidate = (mtl_path.parent / reference).resolve()
            if candidate.is_file() and candidate.suffix.lower() in TEXTURE_EXTENSIONS:
                textures.append(candidate)
    return stable_unique_paths(textures)


def split_material_references(value: str) -> list[str]:
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = value.split()
    if len(parts) <= 1:
        return parts
    references: list[str] = []
    current: list[str] = []
    for token in parts:
        current.append(token)
        if token.lower().endswith(".mtl"):
            references.append(" ".join(current))
            current = []
    if current and not references:
        references.append(" ".join(current))
    return references


def parse_mtl_texture_references(mtl_path: Path) -> list[str]:
    references: list[str] = []
    for raw_line in mtl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            tokens = line.split()
        if len(tokens) < 2 or tokens[0].lower() not in MTL_TEXTURE_KEYS:
            continue
        texture = first_texture_token(tokens[1:])
        if texture:
            references.append(texture)
    return references


def first_texture_token(tokens: list[str]) -> str | None:
    for token in reversed(tokens):
        if Path(token).suffix.lower() in TEXTURE_EXTENSIONS:
            return token
    return tokens[-1] if tokens and not tokens[-1].startswith("-") else None


def find_gltf_texture_files(gltf_path: Path) -> list[Path]:
    try:
        payload = json.loads(gltf_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    textures: list[Path] = []
    for image in payload.get("images", []):
        uri = image.get("uri") if isinstance(image, dict) else None
        if not isinstance(uri, str) or uri.startswith("data:"):
            continue
        candidate = (gltf_path.parent / uri).resolve()
        if candidate.is_file() and candidate.suffix.lower() in TEXTURE_EXTENSIONS:
            textures.append(candidate)
    return stable_unique_paths(textures)


def stable_unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def unique_texture_path(textures_dir: Path, asset_slug: str, source_name: str) -> Path:
    source = Path(source_name)
    stem = slugify(source.stem, "texture")
    suffix = source.suffix.lower() if source.suffix.lower() in TEXTURE_EXTENSIONS else ".png"
    base_name = f"{asset_slug}_{stem}{suffix}"
    candidate = textures_dir / base_name
    index = 2
    while candidate.exists():
        candidate = textures_dir / f"{asset_slug}_{stem}_{index}{suffix}"
        index += 1
    return candidate


def generate_package(
    *,
    task: dict[str, Any],
    mesh_path: Path,
    output_dir: Path,
    public_base_url: str,
    default_density_kg_m3: float,
    default_friction: float,
    capture_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    textures_dir = output_dir / "textures"
    assets_dir.mkdir(exist_ok=True)
    textures_dir.mkdir(exist_ok=True)

    asset_slug = slugify(task["name"], "asset")
    raw_mesh = load_mesh(mesh_path)
    texture_files = extract_texture_assets(mesh_path, raw_mesh, textures_dir, asset_slug)
    cleanup = cleanup_mesh_for_export(raw_mesh)
    mesh = cleanup.mesh
    collision_assets = make_collision_assets(mesh)
    visual_obj = assets_dir / f"{asset_slug}_visual.obj"
    visual_glb = assets_dir / f"{asset_slug}_visual.glb"
    mesh.export(visual_obj)
    mesh.export(visual_glb)
    collision_obj, collision_meshes = export_collision_assets(collision_assets, assets_dir, asset_slug)

    metrics = mesh_metrics(mesh, collision_assets)
    mass_kg, mass_source = estimate_mass(mesh, task.get("mass_kg"), default_density_kg_m3)
    friction = float(task["friction"]) if task.get("friction") is not None else float(default_friction)
    inertia = box_inertia(mass_kg, metrics["extents_m"])
    object_name = task["name"].strip() or asset_slug
    material_metadata = resolve_material_metadata(task["category"], task)
    physics = {
        "mass_kg": mass_kg,
        "mass_source": mass_source,
        "friction": friction,
        "inertia_diagonal": inertia,
        "material_source": "estimated",
        **material_metadata,
    }
    scene = {
        "unit": "meter",
        "up_axis": "z",
        "objects": [
            {
                "id": "asset_001",
                "name": object_name,
                "category": task["category"],
                **material_metadata,
                "visual_mesh": f"assets/{visual_obj.name}",
                "visual_glb": f"assets/{visual_glb.name}",
                "collision_mesh": f"assets/{collision_obj.name}",
                "collision_meshes": collision_meshes,
                "texture_files": texture_files,
                "pose": {"position": [0.0, 0.0, 0.0], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "scale": [1.0, 1.0, 1.0],
                "mass_kg": mass_kg,
                "friction": friction,
                "inertia_diagonal": inertia,
                "source": {"task_id": task["id"], "input": task["original_filename"], "kind": "mesh"},
                "confidence": {"geometry": 0.86, "material": 0.35, "physics": 0.8 if mass_source == "provided" else 0.45},
            }
        ],
    }
    report = {
        "valid": True,
        "source_kind": "mesh",
        "mesh": metrics,
        "mesh_cleanup": cleanup.report,
        "physics": physics,
        "quality": {
            "visual_collision_split": True,
            "textures_present": bool(texture_files),
            "texture_files": texture_files,
            "scale_source": "mesh_units_meter_assumed",
        },
    }
    if capture_quality is not None:
        report["capture_quality"] = capture_quality
    write_exports(output_dir, scene, report, [mesh])
    artifacts = collect_artifacts(output_dir, task["id"], public_base_url)
    return {"scene": scene, "report": report, "artifacts": artifacts}


def generate_roomplan_package(
    *,
    task: dict[str, Any],
    roomplan: dict[str, Any],
    output_dir: Path,
    public_base_url: str,
    default_density_kg_m3: float,
    default_friction: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    textures_dir = output_dir / "textures"
    assets_dir.mkdir(exist_ok=True)
    textures_dir.mkdir(exist_ok=True)

    source_objects = normalize_roomplan_entries(roomplan.get("objects", []), default_category=task["category"])
    source_surfaces = normalize_roomplan_entries(roomplan.get("surfaces", []) or roomplan.get("static_geometry", []), default_category="surface")
    if not source_objects and not source_surfaces:
        raise ValueError("RoomPlan package contains no objects or surfaces.")

    scene_objects: list[dict[str, Any]] = []
    static_geometry: list[dict[str, Any]] = []
    meshes_for_usd: list[trimesh.Trimesh] = []
    capture_root = Path(roomplan["_capture_root"]) if isinstance(roomplan.get("_capture_root"), str) else None

    for index, surface in enumerate(source_surfaces, start=1):
        geometry_id = surface["id"] or f"surface_{index:03d}"
        dimensions = surface["dimensions"]
        pose = surface["pose"]
        material_metadata = resolve_material_metadata(surface["category"], surface)
        mesh = create_box_mesh(dimensions, pose["position"])
        visual_path = assets_dir / f"{slugify(geometry_id)}_visual.obj"
        collision_path = assets_dir / f"{slugify(geometry_id)}_collision.obj"
        mesh.export(visual_path)
        mesh.export(collision_path)
        meshes_for_usd.append(mesh)
        static_geometry.append(
            {
                "id": geometry_id,
                "name": surface["name"] or geometry_id,
                "category": surface["category"],
                **material_metadata,
                "visual_mesh": f"assets/{visual_path.name}",
                "collision_mesh": f"assets/{collision_path.name}",
                "collision_meshes": [f"assets/{collision_path.name}"],
                "pose": pose,
                "dimensions": dimensions,
                "friction": float(surface.get("friction") or default_friction),
                "source": {"task_id": task["id"], "input": task["original_filename"], "kind": "roomplan_surface"},
            }
        )

    residual_scene_mesh_count = 0
    for mesh_path in find_residual_scene_meshes(roomplan):
        residual_scene_mesh_count += 1
        geometry_id = residual_scene_mesh_id(mesh_path, residual_scene_mesh_count)
        material_metadata = resolve_material_metadata("residual_scene", {"material_category": "architectural_surface"})
        source_mesh = load_mesh(mesh_path)
        cleanup = cleanup_mesh_for_export(source_mesh)
        visual_mesh = cleanup.mesh
        collision_mesh = make_collision_mesh(visual_mesh)
        visual_path = assets_dir / f"{slugify(geometry_id)}_visual.obj"
        visual_glb = assets_dir / f"{slugify(geometry_id)}_visual.glb"
        collision_path = assets_dir / f"{slugify(geometry_id)}_collision.obj"
        visual_mesh.export(visual_path)
        visual_mesh.export(visual_glb)
        collision_mesh.export(collision_path)
        meshes_for_usd.append(visual_mesh)
        static_geometry.append(
            {
                "id": geometry_id,
                "name": geometry_id.replace("_", " "),
                "category": "residual_scene",
                **material_metadata,
                "visual_mesh": f"assets/{visual_path.name}",
                "visual_glb": f"assets/{visual_glb.name}",
                "collision_mesh": f"assets/{collision_path.name}",
                "collision_meshes": [f"assets/{collision_path.name}"],
                "pose": {"position": [0.0, 0.0, 0.0], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "scale": [1.0, 1.0, 1.0],
                "friction": float(default_friction),
                "source": {
                    "task_id": task["id"],
                    "input": task["original_filename"],
                    "kind": "roomplan_scene_mesh",
                    "path": str(mesh_path),
                    "cleanup": cleanup.report,
                },
            }
        )

    object_meshes_for_usd: list[trimesh.Trimesh] = []
    for index, source in enumerate(source_objects, start=1):
        object_id = source["id"] or f"asset_{index:03d}"
        dimensions = source["dimensions"]
        pose = source["pose"]
        material_metadata = resolve_material_metadata(source["category"], source)
        capture_source = source.get("source") if isinstance(source.get("source"), dict) else {}
        source_kind = str(capture_source.get("kind") or "roomplan_object")
        visual_mesh, mesh_source_payload = load_source_surface_mesh(capture_source, dimensions, capture_root)
        collision_mesh = make_collision_mesh(visual_mesh)
        visual_obj = assets_dir / f"{slugify(object_id)}_visual.obj"
        visual_glb = assets_dir / f"{slugify(object_id)}_visual.glb"
        collision_obj = assets_dir / f"{slugify(object_id)}_collision.obj"
        visual_mesh.export(visual_obj)
        visual_mesh.export(visual_glb)
        collision_mesh.export(collision_obj)
        object_meshes_for_usd.append(mesh_with_pose(visual_mesh, pose))
        mass_kg = float(source.get("mass_kg") or np.prod(np.maximum(dimensions, [0.001, 0.001, 0.001])) * default_density_kg_m3)
        friction = float(source.get("friction") or default_friction)
        enriched_capture_source = {**capture_source, **mesh_source_payload}
        scene_objects.append(
            {
                "id": object_id,
                "name": source["name"] or object_id,
                "category": source["category"],
                **material_metadata,
                "visual_mesh": f"assets/{visual_obj.name}",
                "visual_glb": f"assets/{visual_glb.name}",
                "collision_mesh": f"assets/{collision_obj.name}",
                "collision_meshes": [f"assets/{collision_obj.name}"],
                "pose": pose,
                "scale": [1.0, 1.0, 1.0],
                "dimensions": dimensions,
                "mass_kg": mass_kg,
                "friction": friction,
                "inertia_diagonal": box_inertia(mass_kg, dimensions),
                "source": {"task_id": task["id"], "input": task["original_filename"], "kind": source_kind, "capture": enriched_capture_source},
                "confidence": {"geometry": 0.72, "material": 0.25, "physics": 0.55 if source.get("mass_kg") else 0.35},
            }
        )

    scene = {
        "unit": roomplan.get("unit", "meter"),
        "up_axis": roomplan.get("up_axis", "z"),
        "objects": scene_objects,
        "static_geometry": static_geometry,
    }
    report = {
        "valid": True,
        "source_kind": roomplan.get("source_kind", "roomplan"),
        "scene": {
            "object_count": len(scene_objects),
            "static_geometry_count": len(static_geometry),
            "residual_scene_mesh_count": residual_scene_mesh_count,
            "roomplan_json": True,
        },
        "quality": {
            "visual_collision_split": True,
            "textures_present": False,
            "scale_source": "roomplan_metric_dimensions",
        },
    }
    if isinstance(roomplan.get("segmentation"), dict):
        report["segmentation"] = roomplan["segmentation"]
    meshes_for_usd = [*object_meshes_for_usd, *meshes_for_usd]
    write_exports(output_dir, scene, report, meshes_for_usd or [create_box_mesh([0.1, 0.1, 0.1])])
    artifacts = collect_artifacts(output_dir, task["id"], public_base_url)
    return {"scene": scene, "report": report, "artifacts": artifacts}


def find_residual_scene_meshes(roomplan: dict[str, Any]) -> list[Path]:
    capture_root_value = roomplan.get("_capture_root")
    if not isinstance(capture_root_value, str):
        return []
    capture_root = Path(capture_root_value)
    if not capture_root.is_dir():
        return []
    explicit: list[Path] = []
    mesh_references = roomplan.get("scene_meshes") or roomplan.get("residual_scene_meshes") or []
    if isinstance(mesh_references, str):
        mesh_references = [mesh_references]
    if isinstance(mesh_references, list):
        for reference in mesh_references:
            if isinstance(reference, str):
                candidate = (capture_root / reference).resolve()
                if is_safe_residual_mesh_path(candidate, capture_root):
                    explicit.append(candidate)
    discovered = [
        candidate
        for candidate in sorted(capture_root.rglob("*"))
        if candidate.is_file()
        and candidate.suffix.lower() in MESH_EXTENSIONS
        and (candidate.stem.lower() in RESIDUAL_SCENE_MESH_STEMS or "scene_mesh" in candidate.relative_to(capture_root).as_posix().lower().split("/"))
    ]
    return stable_unique_paths([*explicit, *discovered])


def is_safe_residual_mesh_path(candidate: Path, capture_root: Path) -> bool:
    try:
        candidate.relative_to(capture_root.resolve())
    except ValueError:
        return False
    return candidate.is_file() and candidate.suffix.lower() in MESH_EXTENSIONS


def residual_scene_mesh_id(mesh_path: Path, index: int) -> str:
    if index == 1:
        return slugify(mesh_path.stem, "scene_mesh")
    return f"{slugify(mesh_path.stem, 'scene_mesh')}_{index:03d}"


def regenerate_metadata_exports(
    *,
    task: dict[str, Any],
    output_dir: Path,
    public_base_url: str,
) -> dict[str, Any]:
    scene = task["scene"]
    report = task["report"] or {"valid": True}
    if is_parametric_scene(scene):
        meshes = materialize_parametric_scene_assets(scene, output_dir)
    else:
        meshes = [load_mesh(output_dir / obj["visual_mesh"]) for obj in scene["objects"]]
    artifacts = collect_artifacts(output_dir, task["id"], public_base_url)
    write_exports(output_dir, scene, report, meshes)
    artifacts = collect_artifacts(output_dir, task["id"], public_base_url)
    return {"scene": scene, "report": report, "artifacts": artifacts}


def generate_standalone_object_package(
    *,
    task: dict[str, Any],
    object_id: str,
    task_output_dir: Path,
    export_dir: Path,
) -> Path:
    scene = task["scene"]
    source = next((obj for obj in scene.get("objects", []) if obj.get("id") == object_id), None)
    if source is None:
        raise KeyError(object_id)
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)

    standalone_object = copy.deepcopy(source)
    standalone_object["pose"] = standalone_object_pose(standalone_object)
    standalone_object["source"] = {
        "kind": "standalone_scene_object_export",
        "task_id": task["id"],
        "input": task["original_filename"],
        "source_object_id": object_id,
        "capture": source.get("source", {}),
    }
    standalone_scene = {
        "unit": scene.get("unit", "meter"),
        "up_axis": scene.get("up_axis", "z"),
        "objects": [standalone_object],
        "static_geometry": [],
    }
    report = {
        "valid": True,
        "source_kind": "standalone_scene_object",
        "source_task_id": task["id"],
        "source_object_id": object_id,
        "quality": {
            "visual_collision_split": True,
            "textures_present": bool(standalone_object.get("texture_files")),
            "texture_files": standalone_object.get("texture_files", []),
            "scale_source": "source_scene_object",
        },
    }
    if "dimensions" in standalone_object:
        meshes = materialize_parametric_scene_assets(standalone_scene, export_dir)
    else:
        copy_object_asset_references(task_output_dir, export_dir, standalone_object)
        meshes = [load_mesh(export_dir / standalone_object["visual_mesh"])]
    write_exports(export_dir, standalone_scene, report, meshes)
    return export_dir / "real2sim_package.zip"


def standalone_object_pose(obj: dict[str, Any]) -> dict[str, list[float]]:
    if isinstance(obj.get("dimensions"), list) and len(obj["dimensions"]) >= 3:
        height = max(float(obj["dimensions"][2]), 0.001)
        return {"position": [0.0, 0.0, round(height / 2.0, 6)], "quaternion": [1.0, 0.0, 0.0, 0.0]}
    return {"position": [0.0, 0.0, 0.0], "quaternion": [1.0, 0.0, 0.0, 0.0]}


def copy_object_asset_references(source_dir: Path, target_dir: Path, obj: dict[str, Any]) -> None:
    collision_meshes = obj.get("collision_meshes") if isinstance(obj.get("collision_meshes"), list) else []
    texture_files = obj.get("texture_files") if isinstance(obj.get("texture_files"), list) else []
    references = [
        obj.get("visual_mesh"),
        obj.get("visual_glb"),
        obj.get("collision_mesh"),
        *collision_meshes,
        *texture_files,
    ]
    copied: set[str] = set()
    for reference in references:
        if not isinstance(reference, str) or not reference or reference in copied:
            continue
        source = source_dir / reference
        if not source.is_file():
            raise FileNotFoundError(reference)
        target = target_dir / reference
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.add(reference)


def write_exports(output_dir: Path, scene: dict[str, Any], report: dict[str, Any], meshes: list[trimesh.Trimesh]) -> None:
    ensure_scene_material_metadata(scene)
    sync_report_physics_metadata(report, scene)
    manifest = {
        "unit": scene["unit"],
        "up_axis": scene["up_axis"],
        "assets": [
            {
                "id": obj["id"],
                "name": obj["name"],
                "category": obj["category"],
                "material_category": obj["material_category"],
                "material_category_source": obj["material_category_source"],
                "visual_mesh": obj["visual_glb"],
                "visual_obj": obj["visual_mesh"],
                "collision_mesh": obj["collision_mesh"],
                "collision_meshes": obj.get("collision_meshes", [obj["collision_mesh"]]),
                "texture_files": obj.get("texture_files", []),
                "mass_kg": obj["mass_kg"],
                "friction": obj["friction"],
                "pose": obj["pose"],
                "confidence": obj["confidence"],
            }
            for obj in scene["objects"]
        ],
        "static_geometry": scene.get("static_geometry", []),
    }
    object_payload = manifest["assets"][0]
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "asset.json").write_text(json.dumps(object_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "scene.json").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "scene.xml").write_text(render_mjcf(scene), encoding="utf-8")
    (output_dir / "scene.urdf").write_text(render_urdf(scene), encoding="utf-8")
    (output_dir / "scene.usd").write_text(render_usd(scene, meshes), encoding="utf-8")
    write_usdz(output_dir)
    report["simulator_validation"] = validate_simulator_exports(output_dir)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.md").write_text(render_package_readme(scene, report), encoding="utf-8")
    write_zip(output_dir)


def is_parametric_scene(scene: dict[str, Any]) -> bool:
    entries = [*scene.get("objects", []), *scene.get("static_geometry", [])]
    return bool(entries) and all("dimensions" in entry for entry in entries)


def materialize_parametric_scene_assets(scene: dict[str, Any], output_dir: Path) -> list[trimesh.Trimesh]:
    assets_dir = output_dir / "assets"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    meshes: list[trimesh.Trimesh] = []
    for obj in scene.get("objects", []):
        object_slug = slugify(obj["id"], "asset")
        visual_mesh, mesh_source_payload = load_source_surface_mesh(entry_surface_source(obj), obj["dimensions"])
        collision_mesh = make_collision_mesh(visual_mesh)
        visual_obj = assets_dir / f"{object_slug}_visual.obj"
        visual_glb = assets_dir / f"{object_slug}_visual.glb"
        collision_obj = assets_dir / f"{object_slug}_collision.obj"
        visual_mesh.export(visual_obj)
        visual_mesh.export(visual_glb)
        collision_mesh.export(collision_obj)
        obj["visual_mesh"] = f"assets/{visual_obj.name}"
        obj["visual_glb"] = f"assets/{visual_glb.name}"
        obj["collision_mesh"] = f"assets/{collision_obj.name}"
        obj["collision_meshes"] = [f"assets/{collision_obj.name}"]
        obj["inertia_diagonal"] = box_inertia(float(obj["mass_kg"]), [float(value) for value in obj["dimensions"]])
        if mesh_source_payload.get("visual_mesh_source") != "parametric_box":
            source = obj.setdefault("source", {})
            if isinstance(source, dict):
                source["capture"] = {**entry_surface_source(obj), **mesh_source_payload}
        meshes.append(mesh_with_pose(visual_mesh, obj["pose"]))
    for geom in scene.get("static_geometry", []):
        geometry_slug = slugify(geom["id"], "static")
        mesh = create_box_mesh(geom["dimensions"], geom["pose"]["position"])
        visual_path = assets_dir / f"{geometry_slug}_visual.obj"
        collision_path = assets_dir / f"{geometry_slug}_collision.obj"
        mesh.export(visual_path)
        mesh.export(collision_path)
        geom["visual_mesh"] = f"assets/{visual_path.name}"
        geom["collision_mesh"] = f"assets/{collision_path.name}"
        geom["collision_meshes"] = [f"assets/{collision_path.name}"]
        meshes.append(mesh)
    return meshes


def render_mjcf(scene: dict[str, Any]) -> str:
    asset_lines: list[str] = []
    body_lines: list[str] = ['    <geom name="floor" type="plane" size="5 5 0.05" friction="0.8 0.1 0.1"/>']
    for geom in scene.get("static_geometry", []):
        geom_name = slugify(geom["id"], "static")
        static_geom_lines: list[str] = []
        for index, collision_mesh in enumerate(collision_meshes_for(geom), start=1):
            mesh_name = f"{geom_name}_collision_{index:03d}"
            asset_lines.append(f'    <mesh name="{mesh_name}" file="{collision_mesh}"/>')
            static_geom_lines.append(
                f'    <geom name="{mesh_name}" type="mesh" mesh="{mesh_name}" contype="1" conaffinity="1" friction="{geom.get("friction", 0.6):.8g} 0.1 0.1"/>'
            )
        body_lines.extend(static_geom_lines)
    for obj in scene["objects"]:
        geom_name = slugify(obj["name"], "asset")
        inertia = " ".join(f"{value:.8g}" for value in obj["inertia_diagonal"])
        collision_geom_lines: list[str] = []
        for index, collision_mesh in enumerate(collision_meshes_for(obj), start=1):
            mesh_name = f"{geom_name}_collision_{index:03d}"
            asset_lines.append(f'    <mesh name="{mesh_name}" file="{collision_mesh}"/>')
            collision_geom_lines.append(
                f'      <geom name="{mesh_name}" type="mesh" mesh="{mesh_name}" contype="1" conaffinity="1" friction="{obj["friction"]:.8g} 0.1 0.1"/>'
            )
        collision_geoms = "\n".join(collision_geom_lines)
        body_lines.append(
            f'''    <body name="{geom_name}" pos="{_vec(obj["pose"]["position"])}" quat="{_vec(obj["pose"]["quaternion"])}">
      <freejoint/>
      <inertial mass="{obj["mass_kg"]:.8g}" pos="0 0 0" diaginertia="{inertia}"/>
{collision_geoms}
    </body>'''
        )
    assets = "\n".join(asset_lines)
    bodies = "\n".join(body_lines)
    return f"""<mujoco model="real2sim_scene">
  <compiler angle="radian" meshdir="."/>
  <asset>
{assets}
  </asset>
  <worldbody>
{bodies}
  </worldbody>
</mujoco>
"""


def render_urdf(scene: dict[str, Any]) -> str:
    links: list[str] = []
    for obj in scene["objects"]:
        link_name = slugify(obj["name"], "asset")
        inertia = obj["inertia_diagonal"]
        collision_blocks = "\n".join(
            f"""    <collision>
      <origin xyz="0 0 0" rpy="0 0 0"/>
      <geometry><mesh filename="{collision_mesh}" scale="1 1 1"/></geometry>
    </collision>"""
            for collision_mesh in collision_meshes_for(obj)
        )
        links.append(
            f"""  <link name="{link_name}">
    <inertial>
      <origin xyz="0 0 0" rpy="0 0 0"/>
      <mass value="{obj["mass_kg"]:.8g}"/>
      <inertia ixx="{inertia[0]:.8g}" ixy="0" ixz="0" iyy="{inertia[1]:.8g}" iyz="0" izz="{inertia[2]:.8g}"/>
    </inertial>
    <visual>
      <origin xyz="0 0 0" rpy="0 0 0"/>
      <geometry><mesh filename="{obj["visual_mesh"]}" scale="1 1 1"/></geometry>
    </visual>
{collision_blocks}
  </link>"""
        )
    rendered_links = "\n".join(links)
    return f"""<?xml version="1.0"?>
<robot name="real2sim_scene">
{rendered_links}
</robot>
"""


def collision_meshes_for(entry: dict[str, Any]) -> list[str]:
    meshes = entry.get("collision_meshes")
    if isinstance(meshes, list) and meshes:
        return [str(mesh) for mesh in meshes]
    return [str(entry["collision_mesh"])]


def render_usd(scene: dict[str, Any], meshes: list[trimesh.Trimesh]) -> str:
    mesh_blocks: list[str] = []
    names = [slugify(obj["name"], "asset") for obj in scene["objects"]]
    names += [slugify(geom["id"], "static") for geom in scene.get("static_geometry", [])]
    for index, mesh in enumerate(meshes):
        points = ",\n        ".join(f"({v[0]:.8g}, {v[1]:.8g}, {v[2]:.8g})" for v in mesh.vertices)
        face_counts = ", ".join(str(len(face)) for face in mesh.faces)
        face_indices = ", ".join(str(int(face_index)) for face in mesh.faces for face_index in face)
        mesh_name = names[index] if index < len(names) else f"mesh_{index:03d}"
        mesh_blocks.append(
            f'''    def Mesh "{mesh_name}"
    {{
        point3f[] points = [
        {points}
        ]
        int[] faceVertexCounts = [{face_counts}]
        int[] faceVertexIndices = [{face_indices}]
        uniform token subdivisionScheme = "none"
    }}'''
        )
    blocks = "\n\n".join(mesh_blocks)
    return f"""#usda 1.0
(
    defaultPrim = "Real2SimScene"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "Real2SimScene"
{{
{blocks}
}}
"""


def render_package_readme(scene: dict[str, Any], report: dict[str, Any]) -> str:
    obj = scene["objects"][0]
    return f"""# Real2Sim Export Package

This package was generated from a real uploaded capture asset.

- Object: {obj["name"]}
- Category: {obj["category"]}
- Material category: {obj.get("material_category", "unknown")} ({obj.get("material_category_source", "not_provided")})
- Unit: {scene["unit"]}
- Visual mesh: `{obj["visual_mesh"]}`
- Collision mesh: `{obj["collision_mesh"]}`
- MJCF: `scene.xml`
- URDF: `scene.urdf`
- USD: `scene.usd`
- USDZ: `scene.usdz`
- Report valid: `{str(report.get("valid", False)).lower()}`

The visual and collision meshes are intentionally separate so robotics simulators can use stable contact geometry without rendering the low-detail collision asset.
"""


def write_usdz(output_dir: Path) -> None:
    usdz_path = output_dir / "scene.usdz"
    if usdz_path.exists():
        usdz_path.unlink()
    entries = [output_dir / "scene.usd"]
    for folder in ["assets", "textures"]:
        root = output_dir / folder
        if root.exists():
            entries.extend(path for path in sorted(root.rglob("*")) if path.is_file())
    with zipfile.ZipFile(usdz_path, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for path in entries:
            if path.is_file():
                archive.write(path, path.relative_to(output_dir).as_posix())


def write_zip(output_dir: Path) -> None:
    package_path = output_dir / "real2sim_package.zip"
    if package_path.exists():
        package_path.unlink()
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path.name != package_path.name:
                archive.write(path, path.relative_to(output_dir).as_posix())


def collect_artifacts(output_dir: Path, task_id: str, public_base_url: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output_dir).as_posix()
        artifacts.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "url": artifact_url(public_base_url, task_id, relative),
            }
        )
    return artifacts


def find_mesh_in_capture(path: Path, work_dir: Path) -> Path | None:
    if path.suffix.lower() in MESH_EXTENSIONS:
        return path
    if path.suffix.lower() != ".zip":
        return None
    extract_dir = work_dir / "capture_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    with zipfile.ZipFile(path) as archive:
        archive.extractall(extract_dir)
    meshes = sorted(candidate for candidate in extract_dir.rglob("*") if candidate.suffix.lower() in MESH_EXTENSIONS)
    return meshes[0] if meshes else None


def normalize_roomplan_entries(entries: list[dict[str, Any]], default_category: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        dimensions = entry.get("dimensions") or entry.get("size") or entry.get("extent")
        if isinstance(dimensions, dict):
            dimensions = [dimensions.get("x", 0.1), dimensions.get("y", 0.1), dimensions.get("z", 0.1)]
        if not isinstance(dimensions, list) or len(dimensions) < 3:
            dimensions = [0.1, 0.1, 0.1]
        pose = normalize_pose(entry.get("pose") or entry.get("transform"))
        normalized.append(
            {
                **entry,
                "id": str(entry.get("id") or entry.get("identifier") or f"{default_category}_{index:03d}"),
                "name": str(entry.get("name") or entry.get("category") or f"{default_category}_{index:03d}"),
                "category": str(entry.get("category") or default_category),
                "dimensions": [float(dimensions[0]), float(dimensions[1]), float(dimensions[2])],
                "pose": pose,
            }
        )
    return normalized


def normalize_pose(value: Any) -> dict[str, list[float]]:
    if isinstance(value, dict):
        position = value.get("position") or value.get("translation") or [0.0, 0.0, 0.0]
        quaternion = value.get("quaternion") or [1.0, 0.0, 0.0, 0.0]
        return {
            "position": [float(position[0]), float(position[1]), float(position[2])],
            "quaternion": [float(quaternion[0]), float(quaternion[1]), float(quaternion[2]), float(quaternion[3])],
        }
    if isinstance(value, list) and len(value) == 16:
        return {
            "position": [float(value[12]), float(value[13]), float(value[14])],
            "quaternion": [1.0, 0.0, 0.0, 0.0],
        }
    return {"position": [0.0, 0.0, 0.0], "quaternion": [1.0, 0.0, 0.0, 0.0]}


def validate_simulator_exports(output_dir: Path) -> dict[str, Any]:
    mjcf_path = output_dir / "scene.xml"
    validation: dict[str, Any] = {
        "mjcf": {
            "xml_parse_valid": False,
            "mujoco_load_valid": False,
            "step_valid": False,
            "mujoco_available": False,
            "error": None,
        }
    }
    try:
        ET.parse(mjcf_path)
        validation["mjcf"]["xml_parse_valid"] = True
    except Exception as exc:
        validation["mjcf"]["error"] = f"xml_parse_failed: {exc}"
        return validation

    try:
        import mujoco  # type: ignore

        validation["mjcf"]["mujoco_available"] = True
        model = mujoco.MjModel.from_xml_path(str(mjcf_path))
        data = mujoco.MjData(model)
        for _ in range(50):
            mujoco.mj_step(model, data)
            if not np.all(np.isfinite(data.qpos)) or not np.all(np.isfinite(data.qvel)):
                raise ValueError("MuJoCo state became non-finite during step validation.")
        validation["mjcf"]["mujoco_load_valid"] = True
        validation["mjcf"]["step_valid"] = True
        validation["mjcf"]["steps"] = 50
        validation["mjcf"]["contact_count"] = int(data.ncon)
        validation["mjcf"]["nbody"] = int(model.nbody)
        validation["mjcf"]["ngeom"] = int(model.ngeom)
    except Exception as exc:
        validation["mjcf"]["error"] = f"mujoco_load_failed: {exc}"
    return validation


def _vec(values: list[float]) -> str:
    return " ".join(f"{value:.8g}" for value in values)
