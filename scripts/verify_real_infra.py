from __future__ import annotations

import json
import os
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np

from app.queue import run_queued_once
from app.settings import AppSettings


BOX_OBJ = """v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 0 0 1
v 1 0 1
v 1 1 1
v 0 1 1
f 1 2 3
f 1 3 4
f 5 8 7
f 5 7 6
f 1 5 6
f 1 6 2
f 2 6 7
f 2 7 3
f 3 7 8
f 3 8 4
f 4 8 5
f 4 5 1
"""


def main() -> None:
    api_base = os.environ.get("REAL2SIM_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    settings = AppSettings()
    with httpx.Client(timeout=90) as client:
        health = client.get(f"{api_base}/api/health").json()
        require(health["database"]["backend"] == "postgresql" and health["database"]["available"], health["database"])
        require(health["queue"]["backend"] == "redis" and health["queue"]["available"], health["queue"])
        require(health["storage_backend"]["backend"] == "s3" and health["storage_backend"]["available"], health["storage_backend"])

        project = client.post(f"{api_base}/api/projects", json={"name": "real infra smoke"}).json()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mesh_path = tmp_path / "infra_box.obj"
            mesh_path.write_text(BOX_OBJ, encoding="utf-8")
            with mesh_path.open("rb") as mesh_file:
                task = client.post(
                    f"{api_base}/api/tasks",
                    data={
                        "project_id": project["id"],
                        "name": "redis minio postgres box",
                        "mode": "asset",
                        "category": "box",
                        "material_category": "corrugated_cardboard",
                    },
                    files={"capture": ("infra_box.obj", mesh_file, "model/obj")},
                ).json()
            rgbd_zip = tmp_path / "infra_rgbd_clusters.zip"
            write_depth_cluster_capture(rgbd_zip, tmp_path)
            with rgbd_zip.open("rb") as capture_file:
                scene_task = client.post(
                    f"{api_base}/api/tasks",
                    data={
                        "project_id": project["id"],
                        "name": "redis minio postgres rgbd clusters",
                        "mode": "scene",
                        "category": "object",
                    },
                    files={"capture": ("infra_rgbd_clusters.zip", capture_file, "application/zip")},
                ).json()
            roomplan_zip = tmp_path / "infra_roomplan_scene_mesh.zip"
            write_roomplan_residual_scene_mesh_capture(roomplan_zip, tmp_path)
            with roomplan_zip.open("rb") as capture_file:
                roomplan_task = client.post(
                    f"{api_base}/api/tasks",
                    data={
                        "project_id": project["id"],
                        "name": "redis minio postgres roomplan residual mesh",
                        "mode": "scene",
                        "category": "room",
                    },
                    files={"capture": ("infra_roomplan_scene_mesh.zip", capture_file, "application/zip")},
                ).json()

        enqueue = client.post(f"{api_base}/api/tasks/{task['id']}/enqueue").json()
        require(enqueue["queue"]["ok"] is True and enqueue["queue"]["backend"] == "redis", enqueue)
        worker_result = run_queued_once(settings)
        require(worker_result["processed"] == 1 and worker_result["failed"] == 0, worker_result)
        scene_enqueue = client.post(f"{api_base}/api/tasks/{scene_task['id']}/enqueue").json()
        require(scene_enqueue["queue"]["ok"] is True and scene_enqueue["queue"]["backend"] == "redis", scene_enqueue)
        scene_worker_result = run_queued_once(settings)
        require(scene_worker_result["processed"] == 1 and scene_worker_result["failed"] == 0, scene_worker_result)
        roomplan_enqueue = client.post(f"{api_base}/api/tasks/{roomplan_task['id']}/enqueue").json()
        require(roomplan_enqueue["queue"]["ok"] is True and roomplan_enqueue["queue"]["backend"] == "redis", roomplan_enqueue)
        roomplan_worker_result = run_queued_once(settings)
        require(roomplan_worker_result["processed"] == 1 and roomplan_worker_result["failed"] == 0, roomplan_worker_result)

        completed = client.get(f"{api_base}/api/tasks/{task['id']}").json()
        require(completed["status"] == "completed", completed)
        require(completed["material_category"] == "corrugated_cardboard", completed)
        require(completed["scene"]["objects"][0]["material_category"] == "corrugated_cardboard", completed["scene"])
        require(completed["report"]["physics"]["material_category"] == "corrugated_cardboard", completed["report"])
        scene_xml = next(artifact for artifact in completed["artifacts"] if artifact["path"] == "scene.xml")
        scene_usdz = next(artifact for artifact in completed["artifacts"] if artifact["path"] == "scene.usdz")
        manifest_artifact = next(artifact for artifact in completed["artifacts"] if artifact["path"] == "manifest.json")
        asset_artifact = next(artifact for artifact in completed["artifacts"] if artifact["path"] == "asset.json")
        require(str(scene_xml.get("storage_url", "")).startswith(settings.s3_public_base_url or "s3://"), scene_xml)
        require(str(scene_usdz.get("storage_url", "")).startswith(settings.s3_public_base_url or "s3://"), scene_usdz)
        require(str(manifest_artifact.get("storage_url", "")).startswith(settings.s3_public_base_url or "s3://"), manifest_artifact)
        if settings.s3_public_base_url:
            manifest = client.get(manifest_artifact["storage_url"]).json()
            asset = client.get(asset_artifact["storage_url"]).json()
            require(manifest["assets"][0]["material_category"] == "corrugated_cardboard", manifest)
            require(asset["material_category"] == "corrugated_cardboard", asset)
            stored = client.get(scene_xml["storage_url"])
            require(stored.status_code == 200 and "<mujoco" in stored.text, {"status_code": stored.status_code, "text": stored.text[:200]})
            stored_usdz = client.get(scene_usdz["storage_url"])
            require(
                stored_usdz.status_code == 200 and stored_usdz.content.startswith(b"PK"),
                {"status_code": stored_usdz.status_code, "bytes": stored_usdz.content[:8].hex()},
            )

        verified = client.post(f"{api_base}/api/tasks/{task['id']}/verify-simulation").json()
        validation = verified["report"]["package_validation"]
        require(validation["valid"] is True and validation["mjcf"]["step_valid"] is True and validation["usdz"]["valid"] is True, validation)
        completed_scene = client.get(f"{api_base}/api/tasks/{scene_task['id']}").json()
        require(completed_scene["status"] == "completed", completed_scene)
        require(completed_scene["report"]["source_kind"] == "rgbd_clustering", completed_scene["report"])
        require(completed_scene["report"]["segmentation"]["object_count"] == 2, completed_scene["report"])
        require([obj["id"] for obj in completed_scene["scene"]["objects"]] == ["cluster_001", "cluster_002"], completed_scene["scene"])
        scene_manifest_artifact = next(artifact for artifact in completed_scene["artifacts"] if artifact["path"] == "manifest.json")
        if settings.s3_public_base_url:
            scene_manifest = client.get(scene_manifest_artifact["storage_url"]).json()
            require({asset["id"] for asset in scene_manifest["assets"]} == {"cluster_001", "cluster_002"}, scene_manifest)
        verified_scene = client.post(f"{api_base}/api/tasks/{scene_task['id']}/verify-simulation").json()
        scene_validation = verified_scene["report"]["package_validation"]
        require(scene_validation["valid"] is True and scene_validation["mjcf"]["step_valid"] is True, scene_validation)
        object_export = client.post(f"{api_base}/api/tasks/{scene_task['id']}/scene/objects/cluster_001/export")
        require(object_export.status_code == 200 and object_export.headers.get("content-type") == "application/zip", object_export.text[:200])
        with zipfile.ZipFile(BytesIO(object_export.content)) as archive:
            names = set(archive.namelist())
            require("assets/cluster_001_visual.obj" in names and "scene.xml" in names and "scene.usdz" in names, sorted(names))
            require(not any(name.startswith("assets/cluster_002") for name in names), sorted(names))
            standalone_manifest = json.loads(archive.read("manifest.json"))
            standalone_report = json.loads(archive.read("report.json"))
            require([asset["id"] for asset in standalone_manifest["assets"]] == ["cluster_001"], standalone_manifest)
            require(standalone_report["simulator_validation"]["mjcf"]["step_valid"] is True, standalone_report)
        completed_roomplan = client.get(f"{api_base}/api/tasks/{roomplan_task['id']}").json()
        require(completed_roomplan["status"] == "completed", completed_roomplan)
        require(completed_roomplan["report"]["scene"]["residual_scene_mesh_count"] == 1, completed_roomplan["report"])
        residual = next(entry for entry in completed_roomplan["scene"]["static_geometry"] if entry["id"] == "scene_mesh")
        require(residual["source"]["kind"] == "roomplan_scene_mesh", residual)
        roomplan_manifest_artifact = next(artifact for artifact in completed_roomplan["artifacts"] if artifact["path"] == "manifest.json")
        if settings.s3_public_base_url:
            roomplan_manifest = client.get(roomplan_manifest_artifact["storage_url"]).json()
            roomplan_residual = next(entry for entry in roomplan_manifest["static_geometry"] if entry["id"] == "scene_mesh")
            require(roomplan_residual["visual_mesh"] == "assets/scene_mesh_visual.obj", roomplan_manifest)
        verified_roomplan = client.post(f"{api_base}/api/tasks/{roomplan_task['id']}/verify-simulation").json()
        roomplan_validation = verified_roomplan["report"]["package_validation"]
        require(roomplan_validation["valid"] is True and roomplan_validation["mjcf"]["step_valid"] is True, roomplan_validation)

    print(f"task_id={task['id']}")
    print(f"scene_task_id={scene_task['id']}")
    print(f"roomplan_task_id={roomplan_task['id']}")
    print(f"database={health['database']['backend']}:available")
    print(f"queue={health['queue']['backend']}:available")
    print(f"storage={health['storage_backend']['backend']}:available")
    print(f"worker={worker_result}")
    print(f"scene_worker={scene_worker_result}")
    print(f"roomplan_worker={roomplan_worker_result}")
    print(f"storage_url={scene_xml['storage_url']}")
    print(f"usdz_storage_url={scene_usdz['storage_url']}")
    print(f"package_valid={validation['valid']}")
    print(f"scene_package_valid={scene_validation['valid']}")
    print(f"roomplan_residual_mesh_package_valid={roomplan_validation['valid']}")
    print("standalone_object_export=cluster_001:valid")


def write_depth_cluster_capture(zip_path: Path, tmp_path: Path) -> None:
    depth = np.array(
        [
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0],
            [0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    depth_path = tmp_path / "frame_001.npy"
    np.save(depth_path, depth)
    intrinsics = {"width": 8, "height": 4, "fx": 20.0, "fy": 20.0, "cx": 3.5, "cy": 1.5, "depth_scale": 1.0}
    surfaces = [
        {
            "id": "table_001",
            "name": "table",
            "category": "table",
            "dimensions": [3.0, 2.0, 0.05],
            "pose": {"position": [0, 0, 0.9745], "quaternion": [1, 0, 0, 0]},
        }
    ]
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(depth_path, "depth/frame_001.npy")
        archive.writestr("intrinsics.json", json.dumps(intrinsics))
        archive.writestr("surfaces.json", json.dumps(surfaces))


def write_roomplan_residual_scene_mesh_capture(zip_path: Path, tmp_path: Path) -> None:
    scene_mesh = tmp_path / "scene_mesh.obj"
    scene_mesh.write_text(BOX_OBJ, encoding="utf-8")
    roomplan = {
        "unit": "meter",
        "up_axis": "z",
        "surfaces": [
            {
                "id": "floor_001",
                "name": "floor",
                "category": "floor",
                "dimensions": [3.0, 2.0, 0.05],
                "pose": {"position": [0.0, 0.0, -0.025], "quaternion": [1.0, 0.0, 0.0, 0.0]},
            }
        ],
        "objects": [
            {
                "id": "box_001",
                "name": "box",
                "category": "box",
                "dimensions": [0.2, 0.2, 0.2],
                "pose": {"position": [0.0, 0.0, 0.1], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "mass_kg": 0.4,
                "friction": 0.6,
            }
        ],
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("roomplan.json", json.dumps(roomplan))
        archive.write(scene_mesh, "scene_mesh.obj")


def require(condition: bool, payload: object) -> None:
    if not condition:
        raise SystemExit(f"real infra verification failed: {payload}")


if __name__ == "__main__":
    main()
