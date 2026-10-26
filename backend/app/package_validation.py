from __future__ import annotations

import json
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .exporters import validate_simulator_exports
from .simulator_adapters import run_native_simulator_validations


REQUIRED_PACKAGE_PATHS = {
    "manifest.json",
    "asset.json",
    "scene.json",
    "scene.xml",
    "scene.urdf",
    "scene.usd",
    "scene.usdz",
    "report.json",
    "README.md",
    "real2sim_package.zip",
}


def validate_export_package(output_dir: Path, settings: Any | None = None) -> dict[str, Any]:
    artifact_completeness = validate_artifact_completeness(output_dir)
    manifest_validation = validate_manifest(output_dir)
    mjcf_validation = validate_simulator_exports(output_dir)["mjcf"]
    urdf_validation = validate_urdf(output_dir)
    usd_validation = validate_usd_ascii(output_dir)
    usdz_validation = validate_usdz_package(output_dir)
    contact_validation = validate_contact_relationships(output_dir)
    zip_validation = validate_package_zip(output_dir)
    native_simulator_validation = (
        run_native_simulator_validations(settings, output_dir)
        if settings is not None
        else {
            "valid": False,
            "configured_count": 0,
            "motrixsim": {"command_configured": False, "attempted": False, "valid": False, "reason": "settings_required"},
            "isaacsim": {"command_configured": False, "attempted": False, "valid": False, "reason": "settings_required"},
            "genesis": {"command_configured": False, "attempted": False, "valid": False, "reason": "settings_required"},
        }
    )
    sections = [
        artifact_completeness,
        manifest_validation,
        mjcf_validation,
        urdf_validation,
        usd_validation,
        usdz_validation,
        contact_validation,
        zip_validation,
    ]
    return {
        "valid": all(section_valid(section) for section in sections),
        "artifact_completeness": artifact_completeness,
        "manifest": manifest_validation,
        "mjcf": mjcf_validation,
        "urdf": urdf_validation,
        "usd": usd_validation,
        "usdz": usdz_validation,
        "contact_relationships": contact_validation,
        "zip": zip_validation,
        "native_simulators": native_simulator_validation,
    }


def validate_artifact_completeness(output_dir: Path) -> dict[str, Any]:
    present = {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_file()}
    missing = sorted(REQUIRED_PACKAGE_PATHS - present)
    asset_files = sorted(path for path in present if path.startswith("assets/"))
    texture_files = sorted(path for path in present if path.startswith("textures/"))
    return {
        "valid": not missing and bool(asset_files),
        "missing": missing,
        "asset_file_count": len(asset_files),
        "texture_file_count": len(texture_files),
        "artifact_count": len(present),
    }


def validate_manifest(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assets = manifest["assets"]
        if not isinstance(assets, list) or not assets:
            raise ValueError("manifest.assets must be a non-empty list")
        missing_references: list[str] = []
        missing_texture_references: list[str] = []
        invalid_assets: list[str] = []
        for asset in assets:
            asset_id = str(asset.get("id") or "unknown")
            for key in ["visual_mesh", "visual_obj", "collision_mesh"]:
                referenced = asset.get(key)
                if not isinstance(referenced, str) or not (output_dir / referenced).is_file():
                    missing_references.append(f"{asset_id}:{key}:{referenced}")
            collision_meshes = asset.get("collision_meshes", [])
            if collision_meshes:
                if not isinstance(collision_meshes, list):
                    missing_references.append(f"{asset_id}:collision_meshes:not_list")
                else:
                    for collision_mesh in collision_meshes:
                        if not isinstance(collision_mesh, str) or not (output_dir / collision_mesh).is_file():
                            missing_references.append(f"{asset_id}:collision_meshes:{collision_mesh}")
            for texture in asset.get("texture_files", []):
                if not isinstance(texture, str) or not (output_dir / texture).is_file():
                    missing_texture_references.append(f"{asset_id}:texture:{texture}")
            if not is_positive_number(asset.get("mass_kg")) or not is_non_negative_number(asset.get("friction")):
                invalid_assets.append(asset_id)
            pose = asset.get("pose", {})
            if not isinstance(pose, dict) or len(pose.get("position", [])) != 3 or len(pose.get("quaternion", [])) != 4:
                invalid_assets.append(f"{asset_id}:pose")
        return {
            "valid": not missing_references and not missing_texture_references and not invalid_assets,
            "asset_count": len(assets),
            "missing_references": missing_references,
            "missing_texture_references": missing_texture_references,
            "invalid_assets": invalid_assets,
        }
    except Exception as exc:
        return {
            "valid": False,
            "asset_count": 0,
            "missing_references": [],
            "missing_texture_references": [],
            "invalid_assets": [],
            "error": str(exc),
        }


def validate_urdf(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "scene.urdf"
    try:
        root = ET.parse(path).getroot()
        if root.tag != "robot":
            raise ValueError("URDF root is not robot")
        links = root.findall("link")
        missing_meshes: list[str] = []
        invalid_links: list[str] = []
        for link in links:
            link_name = link.attrib.get("name", "unnamed")
            if link.find("inertial") is None:
                invalid_links.append(f"{link_name}:missing_inertial")
            for mesh in link.findall(".//mesh"):
                filename = mesh.attrib.get("filename")
                if not filename or not (output_dir / filename).is_file():
                    missing_meshes.append(f"{link_name}:{filename}")
        return {
            "valid": bool(links) and not missing_meshes and not invalid_links,
            "link_count": len(links),
            "missing_meshes": missing_meshes,
            "invalid_links": invalid_links,
        }
    except Exception as exc:
        return {"valid": False, "link_count": 0, "missing_meshes": [], "invalid_links": [], "error": str(exc)}


def validate_usd_ascii(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "scene.usd"
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("#usda 1.0"):
            raise ValueError("USD file is not ASCII USDA 1.0")
        mesh_defs = re.findall(r'def Mesh "([^"]+)"', text)
        point_blocks = re.findall(r"point3f\[\] points\s*=\s*\[(.*?)\]", text, flags=re.S)
        face_count_blocks = re.findall(r"int\[\] faceVertexCounts\s*=\s*\[(.*?)\]", text, flags=re.S)
        face_index_blocks = re.findall(r"int\[\] faceVertexIndices\s*=\s*\[(.*?)\]", text, flags=re.S)
        if not mesh_defs:
            raise ValueError("USD contains no Mesh prims")
        if not (len(mesh_defs) == len(point_blocks) == len(face_count_blocks) == len(face_index_blocks)):
            raise ValueError("USD mesh arrays are incomplete")
        return {
            "valid": True,
            "mesh_count": len(mesh_defs),
            "point_block_count": len(point_blocks),
            "face_block_count": len(face_count_blocks),
        }
    except Exception as exc:
        return {"valid": False, "mesh_count": 0, "point_block_count": 0, "face_block_count": 0, "error": str(exc)}


def validate_usdz_package(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "scene.usdz"
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            bad_file = archive.testzip()
            compressed = [info.filename for info in archive.infolist() if info.compress_type != zipfile.ZIP_STORED]
        missing = sorted({"scene.usd"} - names)
        return {
            "valid": not missing and bad_file is None and not compressed,
            "missing": missing,
            "bad_file": bad_file,
            "compressed_entries": compressed,
            "entry_count": len(names),
        }
    except Exception as exc:
        return {"valid": False, "missing": [], "bad_file": None, "compressed_entries": [], "entry_count": 0, "error": str(exc)}


def validate_contact_relationships(output_dir: Path, gap_tolerance_m: float = 0.03, penetration_tolerance_m: float = 0.02) -> dict[str, Any]:
    try:
        scene = json.loads((output_dir / "scene.json").read_text(encoding="utf-8"))
        objects = [entry for entry in scene.get("objects", []) if has_parametric_box(entry)]
        static_geometry = [entry for entry in scene.get("static_geometry", []) if has_parametric_box(entry)]
        if not objects:
            return {
                "valid": True,
                "skipped": True,
                "reason": "no_parametric_scene_objects",
                "parametric_object_count": 0,
                "support_relations": [],
                "unsupported_objects": [],
            }

        support_candidates = [*static_geometry, *objects]
        support_relations: list[dict[str, Any]] = []
        unsupported: list[str] = []
        diagnostics: list[dict[str, Any]] = []
        for obj in objects:
            relation = best_support_relation(obj, support_candidates, gap_tolerance_m, penetration_tolerance_m)
            if relation is None:
                unsupported.append(str(obj.get("id") or obj.get("name") or "unknown"))
                diagnostics.append(unsupported_diagnostic(obj, support_candidates))
            else:
                support_relations.append(relation)

        return {
            "valid": not unsupported,
            "skipped": False,
            "gap_tolerance_m": gap_tolerance_m,
            "penetration_tolerance_m": penetration_tolerance_m,
            "parametric_object_count": len(objects),
            "support_relation_count": len(support_relations),
            "support_relations": support_relations,
            "unsupported_objects": unsupported,
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        return {
            "valid": False,
            "skipped": False,
            "parametric_object_count": 0,
            "support_relations": [],
            "unsupported_objects": [],
            "error": str(exc),
        }


def has_parametric_box(entry: dict[str, Any]) -> bool:
    dimensions = entry.get("dimensions")
    pose = entry.get("pose", {})
    position = pose.get("position") if isinstance(pose, dict) else None
    return isinstance(dimensions, list) and len(dimensions) >= 3 and isinstance(position, list) and len(position) >= 3


def best_support_relation(
    obj: dict[str, Any],
    candidates: list[dict[str, Any]],
    gap_tolerance_m: float,
    penetration_tolerance_m: float,
) -> dict[str, Any] | None:
    obj_id = str(obj.get("id") or obj.get("name") or "unknown")
    obj_bounds = box_bounds(obj)
    obj_footprint = max((obj_bounds["max"][0] - obj_bounds["min"][0]) * (obj_bounds["max"][1] - obj_bounds["min"][1]), 1e-9)
    bottom = obj_bounds["min"][2]
    best: dict[str, Any] | None = None
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or candidate.get("name") or "unknown")
        if candidate_id == obj_id:
            continue
        candidate_bounds = box_bounds(candidate)
        support_top = candidate_bounds["max"][2]
        gap = bottom - support_top
        if gap < -penetration_tolerance_m or gap > gap_tolerance_m:
            continue
        overlap_area = horizontal_overlap_area(obj_bounds, candidate_bounds)
        if overlap_area < max(obj_footprint * 0.05, 1e-8):
            continue
        relation = {
            "object_id": obj_id,
            "object_category": str(obj.get("category") or ""),
            "support_id": candidate_id,
            "support_category": str(candidate.get("category") or ""),
            "vertical_gap_m": round(float(gap), 6),
            "horizontal_overlap_area_m2": round(float(overlap_area), 6),
        }
        if best is None or abs(relation["vertical_gap_m"]) < abs(best["vertical_gap_m"]):
            best = relation
    return best


def unsupported_diagnostic(obj: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    obj_id = str(obj.get("id") or obj.get("name") or "unknown")
    obj_bounds = box_bounds(obj)
    nearest: dict[str, Any] | None = None
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or candidate.get("name") or "unknown")
        if candidate_id == obj_id:
            continue
        candidate_bounds = box_bounds(candidate)
        overlap_area = horizontal_overlap_area(obj_bounds, candidate_bounds)
        gap = obj_bounds["min"][2] - candidate_bounds["max"][2]
        distance_score = abs(gap) if overlap_area > 0 else abs(gap) + 10.0
        detail = {
            "support_id": candidate_id,
            "support_category": str(candidate.get("category") or ""),
            "vertical_gap_m": round(float(gap), 6),
            "horizontal_overlap_area_m2": round(float(overlap_area), 6),
            "distance_score": round(float(distance_score), 6),
        }
        if nearest is None or detail["distance_score"] < nearest["distance_score"]:
            nearest = detail
    return {
        "object_id": obj_id,
        "object_category": str(obj.get("category") or ""),
        "nearest_support": nearest,
    }


def box_bounds(entry: dict[str, Any]) -> dict[str, list[float]]:
    dimensions = [float(value) for value in entry["dimensions"][:3]]
    position = [float(value) for value in entry["pose"]["position"][:3]]
    half = [dimension / 2.0 for dimension in dimensions]
    return {
        "min": [position[index] - half[index] for index in range(3)],
        "max": [position[index] + half[index] for index in range(3)],
    }


def horizontal_overlap_area(first: dict[str, list[float]], second: dict[str, list[float]]) -> float:
    overlap_x = max(0.0, min(first["max"][0], second["max"][0]) - max(first["min"][0], second["min"][0]))
    overlap_y = max(0.0, min(first["max"][1], second["max"][1]) - max(first["min"][1], second["min"][1]))
    return overlap_x * overlap_y


def validate_package_zip(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "real2sim_package.zip"
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            bad_file = archive.testzip()
        missing = sorted((REQUIRED_PACKAGE_PATHS - {"real2sim_package.zip"}) - names)
        return {"valid": not missing and bad_file is None, "missing": missing, "bad_file": bad_file, "entry_count": len(names)}
    except Exception as exc:
        return {"valid": False, "missing": [], "bad_file": None, "entry_count": 0, "error": str(exc)}


def section_valid(section: dict[str, Any]) -> bool:
    if "valid" in section:
        return bool(section["valid"])
    return bool(section.get("mujoco_load_valid") and section.get("step_valid"))


def is_positive_number(value: Any) -> bool:
    return isinstance(value, int | float) and math.isfinite(float(value)) and float(value) > 0


def is_non_negative_number(value: Any) -> bool:
    return isinstance(value, int | float) and math.isfinite(float(value)) and float(value) >= 0
