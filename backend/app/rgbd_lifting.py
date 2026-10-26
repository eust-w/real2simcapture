from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image

from .materials import provided_material_category


class RGBDLiftingError(Exception):
    pass


DEPTH_CLUSTER_MAX_NEIGHBOR_DISTANCE_M = 0.18
DEPTH_CLUSTER_MIN_POINTS = 4


def find_rgbd_scene_in_capture(input_path: Path, work_dir: Path, default_category: str) -> dict[str, Any] | None:
    if input_path.suffix.lower() != ".zip":
        return None
    extract_dir = work_dir / "rgbd_lifting_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    with zipfile.ZipFile(input_path) as archive:
        archive.extractall(extract_dir)
    mask_paths = sorted((extract_dir / "masks").glob("*")) if (extract_dir / "masks").exists() else []
    mask_paths = [path for path in mask_paths if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    if mask_paths:
        return lift_rgbd_scene(extract_dir, mask_paths, default_category)
    return cluster_unmasked_rgbd_scene(extract_dir, default_category)


def lift_rgbd_scene(root: Path, mask_paths: list[Path], default_category: str) -> dict[str, Any]:
    intrinsics = read_json(root / "intrinsics.json")
    if not intrinsics:
        raise RGBDLiftingError("rgbd_intrinsics_required")
    object_metadata = read_json(root / "objects.json")
    if not isinstance(object_metadata, dict):
        object_metadata = {}
    surfaces = read_json(root / "surfaces.json")
    if not isinstance(surfaces, list):
        surfaces = []
    poses = read_json(root / "poses.json")
    pose_by_id = pose_lookup(poses)
    objects: list[dict[str, Any]] = []
    for mask_path in mask_paths:
        object_id = mask_path.stem
        depth_path = find_depth_for_mask(root, object_id)
        if depth_path is None:
            raise RGBDLiftingError(f"rgbd_depth_missing:{object_id}")
        points, rows, cols, faces = lift_mask_geometry(mask_path, depth_path, intrinsics, pose_by_id.get(object_id))
        if points.shape[0] == 0:
            raise RGBDLiftingError(f"rgbd_mask_has_no_depth:{object_id}")
        bounds_min = points.min(axis=0)
        bounds_max = points.max(axis=0)
        extents = np.maximum(bounds_max - bounds_min, np.array([0.001, 0.001, 0.001]))
        center = (bounds_min + bounds_max) / 2.0
        surface_mesh = write_rgbd_surface_mesh(root, object_id, points, range(points.shape[0]), faces, center)
        metadata = object_metadata.get(object_id, {}) if isinstance(object_metadata.get(object_id), dict) else {}
        mass_kg = float(metadata.get("mass_kg") or max(float(np.prod(extents)) * 700.0, 0.001))
        friction = float(metadata.get("friction") or 0.6)
        material_category = provided_material_category(metadata)
        material_payload = {"material_category": material_category} if material_category else {}
        objects.append(
            {
                "id": object_id,
                "name": str(metadata.get("name") or object_id),
                "category": str(metadata.get("category") or default_category),
                **material_payload,
                "dimensions": round_vector(extents),
                "pose": {"position": round_vector(center), "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "mass_kg": mass_kg,
                "friction": friction,
                "confidence": {"geometry": 0.68, "material": 0.2, "physics": 0.5 if metadata.get("mass_kg") else 0.35},
                "source": {
                    "kind": "rgbd_lifted_mask",
                    "mask": str(mask_path.relative_to(root)),
                    "depth": str(depth_path.relative_to(root)),
                    "surface_mesh": surface_mesh["relative_path"],
                    "surface_mesh_path": surface_mesh["absolute_path"],
                    "surface_mesh_source": "rgbd_mask_depth_surface",
                    "point_count": int(points.shape[0]),
                    "bounds_min": round_vector(bounds_min),
                    "bounds_max": round_vector(bounds_max),
                },
            }
        )
    if not objects:
        raise RGBDLiftingError("rgbd_no_objects_lifted")
    return {
        "unit": "meter",
        "up_axis": "z",
        "objects": objects,
        "surfaces": surfaces,
        "source_kind": "rgbd_lifting",
        "segmentation": {
            "object_count": len(objects),
            "mask_count": len(mask_paths),
            "has_intrinsics": True,
            "has_poses": bool(pose_by_id),
        },
    }


def lift_mask_points(mask_path: Path, depth_path: Path, intrinsics: dict[str, Any], transform: list[float] | None) -> np.ndarray:
    points, _, _, _ = lift_mask_geometry(mask_path, depth_path, intrinsics, transform)
    return points


def lift_mask_geometry(
    mask_path: Path,
    depth_path: Path,
    intrinsics: dict[str, Any],
    transform: list[float] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mask = np.asarray(Image.open(mask_path).convert("L")) > 0
    depth = load_depth(depth_path, float(intrinsics.get("depth_scale", 1.0)))
    if depth.shape != mask.shape:
        raise RGBDLiftingError(f"rgbd_shape_mismatch:{mask_path.name}:{mask.shape}:{depth.shape}")
    ys, xs = np.nonzero(mask & np.isfinite(depth) & (depth > 0))
    if len(xs) == 0:
        return np.zeros((0, 3), dtype=float), ys, xs, np.zeros((0, 3), dtype=int)
    z = depth[ys, xs].astype(float)
    fx = float(intrinsics["fx"])
    fy = float(intrinsics["fy"])
    cx = float(intrinsics.get("cx", (depth.shape[1] - 1) / 2.0))
    cy = float(intrinsics.get("cy", (depth.shape[0] - 1) / 2.0))
    x = (xs.astype(float) - cx) * z / fx
    y = (ys.astype(float) - cy) * z / fy
    points = np.stack([x, y, z], axis=1)
    if intrinsics.get("camera_convention") == "arkit":
        points *= np.array([1.0, -1.0, -1.0])
    if transform:
        matrix = np.array(transform, dtype=float).reshape(4, 4).T
        homogeneous = np.concatenate([points, np.ones((points.shape[0], 1), dtype=float)], axis=1)
        points = (homogeneous @ matrix.T)[:, :3]
    if intrinsics.get("world_up_axis") == "y":
        points = points[:, [0, 2, 1]] * np.array([1.0, -1.0, 1.0])
    faces = depth_grid_faces(ys, xs, points, depth.shape)
    return points, ys, xs, faces


def cluster_unmasked_rgbd_scene(root: Path, default_category: str) -> dict[str, Any] | None:
    depth_paths = find_depth_frames(root)
    if not depth_paths:
        return None
    intrinsics = read_json(root / "intrinsics.json")
    if not intrinsics:
        raise RGBDLiftingError("rgbd_intrinsics_required")
    surfaces = read_json(root / "surfaces.json")
    if not isinstance(surfaces, list):
        surfaces = []
    poses = read_json(root / "poses.json")
    pose_by_id = pose_lookup(poses)

    objects: list[dict[str, Any]] = []
    rejected_components = 0
    for depth_path in depth_paths:
        transform = pose_for_depth_frame(depth_path, pose_by_id)
        depth = load_depth(depth_path, float(intrinsics.get("depth_scale", 1.0)))
        points, rows, cols = lift_depth_pixels(depth, intrinsics, transform)
        if points.shape[0] == 0:
            continue
        faces = depth_grid_faces(rows, cols, points, depth.shape)
        components = connected_depth_components(
            points=points,
            rows=rows,
            cols=cols,
            shape=depth.shape,
            max_neighbor_distance_m=DEPTH_CLUSTER_MAX_NEIGHBOR_DISTANCE_M,
        )
        for component in components:
            if len(component) < DEPTH_CLUSTER_MIN_POINTS:
                rejected_components += 1
                continue
            component_points = points[np.array(component, dtype=int)]
            bounds_min = component_points.min(axis=0)
            bounds_max = component_points.max(axis=0)
            extents = np.maximum(bounds_max - bounds_min, np.array([0.001, 0.001, 0.001]))
            center = (bounds_min + bounds_max) / 2.0
            object_index = len(objects) + 1
            object_id = f"cluster_{object_index:03d}"
            surface_mesh = write_rgbd_surface_mesh(root, object_id, points, component, faces, center)
            objects.append(
                {
                    "id": object_id,
                    "name": object_id.replace("_", " "),
                    "category": default_category,
                    "dimensions": round_vector(extents),
                    "pose": {"position": round_vector(center), "quaternion": [1.0, 0.0, 0.0, 0.0]},
                    "mass_kg": float(max(float(np.prod(extents)) * 700.0, 0.001)),
                    "friction": 0.6,
                    "confidence": {"geometry": 0.55, "material": 0.1, "physics": 0.3},
                    "source": {
                        "kind": "rgbd_depth_cluster",
                        "depth": str(depth_path.relative_to(root)),
                        "surface_mesh": surface_mesh["relative_path"],
                        "surface_mesh_path": surface_mesh["absolute_path"],
                        "surface_mesh_source": "rgbd_cluster_depth_surface",
                        "point_count": int(component_points.shape[0]),
                        "bounds_min": round_vector(bounds_min),
                        "bounds_max": round_vector(bounds_max),
                    },
                }
            )
    if not objects:
        raise RGBDLiftingError("rgbd_no_depth_clusters")
    return {
        "unit": "meter",
        "up_axis": "z",
        "objects": objects,
        "surfaces": surfaces,
        "source_kind": "rgbd_clustering",
        "segmentation": {
            "provider": "rgbd_depth_clustering",
            "valid": True,
            "object_count": len(objects),
            "cluster_count": len(objects),
            "rejected_component_count": rejected_components,
            "depth_frame_count": len(depth_paths),
            "mask_count": 0,
            "has_intrinsics": True,
            "has_poses": bool(pose_by_id),
            "max_neighbor_distance_m": DEPTH_CLUSTER_MAX_NEIGHBOR_DISTANCE_M,
            "minimum_cluster_points": DEPTH_CLUSTER_MIN_POINTS,
        },
    }


def find_depth_frames(root: Path) -> list[Path]:
    depth_dir = root / "depth"
    if not depth_dir.exists():
        return []
    return sorted(path for path in depth_dir.iterdir() if path.is_file() and path.suffix.lower() in {".npy", ".png", ".tif", ".tiff"})


def pose_for_depth_frame(depth_path: Path, pose_by_id: dict[str, list[float]]) -> list[float] | None:
    for key in [depth_path.stem, depth_path.name, f"depth/{depth_path.name}"]:
        if key in pose_by_id:
            return pose_by_id[key]
    if len(pose_by_id) == 1:
        return next(iter(pose_by_id.values()))
    return None


def lift_depth_pixels(depth: np.ndarray, intrinsics: dict[str, Any], transform: list[float] | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    valid = np.isfinite(depth) & (depth > 0)
    rows, cols = np.nonzero(valid)
    if len(cols) == 0:
        return np.zeros((0, 3), dtype=float), rows, cols
    z = depth[rows, cols].astype(float)
    fx = float(intrinsics["fx"])
    fy = float(intrinsics["fy"])
    cx = float(intrinsics.get("cx", (depth.shape[1] - 1) / 2.0))
    cy = float(intrinsics.get("cy", (depth.shape[0] - 1) / 2.0))
    x = (cols.astype(float) - cx) * z / fx
    y = (rows.astype(float) - cy) * z / fy
    points = np.stack([x, y, z], axis=1)
    if intrinsics.get("camera_convention") == "arkit":
        points *= np.array([1.0, -1.0, -1.0])
    if transform:
        matrix = np.array(transform, dtype=float).reshape(4, 4).T
        homogeneous = np.concatenate([points, np.ones((points.shape[0], 1), dtype=float)], axis=1)
        points = (homogeneous @ matrix.T)[:, :3]
    if intrinsics.get("world_up_axis") == "y":
        points = points[:, [0, 2, 1]] * np.array([1.0, -1.0, 1.0])
    return points, rows, cols


def depth_grid_faces(rows: np.ndarray, cols: np.ndarray, points: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    index_by_pixel = np.full(shape, -1, dtype=int)
    for index, (row, col) in enumerate(zip(rows, cols, strict=True)):
        index_by_pixel[int(row), int(col)] = index
    faces: list[list[int]] = []
    for row in range(shape[0] - 1):
        for col in range(shape[1] - 1):
            top_left = int(index_by_pixel[row, col])
            top_right = int(index_by_pixel[row, col + 1])
            bottom_left = int(index_by_pixel[row + 1, col])
            bottom_right = int(index_by_pixel[row + 1, col + 1])
            if min(top_left, top_right, bottom_left, bottom_right) < 0:
                continue
            faces.append([top_left, bottom_left, bottom_right])
            faces.append([top_left, bottom_right, top_right])
    return np.array(faces, dtype=int)


def write_rgbd_surface_mesh(
    root: Path,
    object_id: str,
    points: np.ndarray,
    point_indices: range | list[int],
    faces: np.ndarray,
    center: np.ndarray,
) -> dict[str, str]:
    indices = list(point_indices)
    index_lookup = {source_index: target_index for target_index, source_index in enumerate(indices)}
    selected_faces = [
        [index_lookup[int(vertex)] for vertex in face]
        for face in faces
        if all(int(vertex) in index_lookup for vertex in face)
    ]
    local_vertices = points[np.array(indices, dtype=int)] - center
    if selected_faces:
        mesh = trimesh.Trimesh(vertices=local_vertices, faces=np.array(selected_faces, dtype=int), process=False)
    else:
        mesh = fallback_bounds_mesh(local_vertices)
    mesh_dir = root / "lifted_meshes"
    mesh_dir.mkdir(exist_ok=True)
    mesh_path = mesh_dir / f"{safe_mesh_id(object_id)}_surface.obj"
    mesh.export(mesh_path)
    return {"relative_path": mesh_path.relative_to(root).as_posix(), "absolute_path": str(mesh_path.resolve())}


def fallback_bounds_mesh(local_vertices: np.ndarray) -> trimesh.Trimesh:
    if local_vertices.shape[0] == 0:
        return trimesh.creation.box(extents=[0.001, 0.001, 0.001])
    bounds_min = local_vertices.min(axis=0)
    bounds_max = local_vertices.max(axis=0)
    extents = np.maximum(bounds_max - bounds_min, np.array([0.001, 0.001, 0.001]))
    transform = np.eye(4)
    transform[:3, 3] = (bounds_min + bounds_max) / 2.0
    return trimesh.creation.box(extents=extents, transform=transform)


def safe_mesh_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower() or "object"


def connected_depth_components(
    *,
    points: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    shape: tuple[int, int],
    max_neighbor_distance_m: float,
) -> list[list[int]]:
    index_by_pixel = np.full(shape, -1, dtype=int)
    for index, (row, col) in enumerate(zip(rows, cols, strict=True)):
        index_by_pixel[int(row), int(col)] = index
    visited = np.zeros(points.shape[0], dtype=bool)
    components: list[list[int]] = []
    for start_index in range(points.shape[0]):
        if visited[start_index]:
            continue
        visited[start_index] = True
        queue = [start_index]
        component: list[int] = []
        while queue:
            index = queue.pop()
            component.append(index)
            row = int(rows[index])
            col = int(cols[index])
            for neighbor_row, neighbor_col in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                if neighbor_row < 0 or neighbor_col < 0 or neighbor_row >= shape[0] or neighbor_col >= shape[1]:
                    continue
                neighbor_index = int(index_by_pixel[neighbor_row, neighbor_col])
                if neighbor_index < 0 or visited[neighbor_index]:
                    continue
                if float(np.linalg.norm(points[index] - points[neighbor_index])) > max_neighbor_distance_m:
                    continue
                visited[neighbor_index] = True
                queue.append(neighbor_index)
        components.append(component)
    return components


def load_depth(depth_path: Path, depth_scale: float) -> np.ndarray:
    if depth_path.suffix.lower() == ".npy":
        depth = np.load(depth_path).astype(float)
    else:
        depth = np.asarray(Image.open(depth_path), dtype=float)
    return depth * depth_scale


def find_depth_for_mask(root: Path, object_id: str) -> Path | None:
    depth_dir = root / "depth"
    if not depth_dir.exists():
        return None
    candidate_ids = depth_candidate_ids(object_id)
    for candidate_id in candidate_ids:
        for suffix in [".npy", ".png", ".tif", ".tiff"]:
            candidate = depth_dir / f"{candidate_id}{suffix}"
            if candidate.is_file():
                return candidate
    candidates = sorted(path for path in depth_dir.iterdir() if path.is_file() and path.suffix.lower() in {".npy", ".png", ".tif", ".tiff"})
    return candidates[0] if len(candidates) == 1 else None


def depth_candidate_ids(object_id: str) -> list[str]:
    candidates = [object_id]
    sam2_match = re.match(r"(.+)_sam2_\d+$", object_id)
    if sam2_match:
        candidates.append(sam2_match.group(1))
    return candidates


def pose_lookup(value: Any) -> dict[str, list[float]]:
    lookup: dict[str, list[float]] = {}
    frames = value.get("frames", []) if isinstance(value, dict) else value if isinstance(value, list) else []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            continue
        frame_id = str(frame.get("id") or frame.get("object_id") or frame.get("mask") or f"frame_{index:05d}")
        transform = frame.get("transform") or frame.get("matrix")
        if isinstance(transform, list) and len(transform) == 16:
            lookup[frame_id] = [float(item) for item in transform]
    return lookup


def read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def round_vector(values: np.ndarray | list[float]) -> list[float]:
    return [round(float(value), 6) for value in values]
