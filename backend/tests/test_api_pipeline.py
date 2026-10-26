import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageFilter
import numpy as np

from app.main import create_app
from app.pipeline import extract_capture_media
from app.quality import analyze_capture_quality
from app.settings import AppSettings


def make_client(tmp_path: Path, extra_settings: dict | None = None) -> TestClient:
    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'real2sim.sqlite3'}",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        public_base_url="http://testserver",
        **(extra_settings or {}),
    )
    return TestClient(create_app(settings))


def write_box_obj(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "v -0.5 -0.5 0.0",
                "v 0.5 -0.5 0.0",
                "v 0.5 0.5 0.0",
                "v -0.5 0.5 0.0",
                "v -0.5 -0.5 1.0",
                "v 0.5 -0.5 1.0",
                "v 0.5 0.5 1.0",
                "v -0.5 0.5 1.0",
                "f 1 2 3",
                "f 1 3 4",
                "f 5 8 7",
                "f 5 7 6",
                "f 1 5 6",
                "f 1 6 2",
                "f 2 6 7",
                "f 2 7 3",
                "f 3 7 8",
                "f 3 8 4",
                "f 4 8 5",
                "f 4 5 1",
            ]
        ),
        encoding="utf-8",
    )


def write_two_box_obj(path: Path) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    def add_box(x0: float, x1: float) -> None:
        offset = len(vertices) + 1
        vertices.extend(
            [
                (x0, -0.5, 0.0),
                (x1, -0.5, 0.0),
                (x1, 0.5, 0.0),
                (x0, 0.5, 0.0),
                (x0, -0.5, 1.0),
                (x1, -0.5, 1.0),
                (x1, 0.5, 1.0),
                (x0, 0.5, 1.0),
            ]
        )
        local_faces = [
            (1, 2, 3),
            (1, 3, 4),
            (5, 8, 7),
            (5, 7, 6),
            (1, 5, 6),
            (1, 6, 2),
            (2, 6, 7),
            (2, 7, 3),
            (3, 7, 8),
            (3, 8, 4),
            (4, 8, 5),
            (4, 5, 1),
        ]
        faces.extend(tuple(offset + index - 1 for index in face) for face in local_faces)

    add_box(-1.0, -0.2)
    add_box(0.2, 1.0)
    path.write_text(
        "\n".join(
            [*(f"v {x} {y} {z}" for x, y, z in vertices), *(f"f {a} {b} {c}" for a, b, c in faces)]
        ),
        encoding="utf-8",
    )


def write_box_with_small_floater_obj(path: Path) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    def add_box(origin: tuple[float, float, float], size: float) -> None:
        x, y, z = origin
        offset = len(vertices) + 1
        vertices.extend(
            [
                (x, y, z),
                (x + size, y, z),
                (x + size, y + size, z),
                (x, y + size, z),
                (x, y, z + size),
                (x + size, y, z + size),
                (x + size, y + size, z + size),
                (x, y + size, z + size),
            ]
        )
        local_faces = [
            (1, 2, 3),
            (1, 3, 4),
            (5, 8, 7),
            (5, 7, 6),
            (1, 5, 6),
            (1, 6, 2),
            (2, 6, 7),
            (2, 7, 3),
            (3, 7, 8),
            (3, 8, 4),
            (4, 8, 5),
            (4, 5, 1),
        ]
        faces.extend(tuple(offset + index - 1 for index in face) for face in local_faces)

    add_box((-0.5, -0.5, 0.0), 1.0)
    add_box((10.0, 10.0, 10.0), 0.02)
    path.write_text(
        "\n".join(
            [*(f"v {x} {y} {z}" for x, y, z in vertices), *(f"f {a} {b} {c}" for a, b, c in faces)]
        ),
        encoding="utf-8",
    )


def create_project(client: TestClient) -> str:
    response = client.post("/api/projects", json={"name": "bench scan"})
    assert response.status_code == 201
    return response.json()["id"]


def test_live_rgbd_session_streams_frames_updates_scene_and_finalizes_task(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)

    create_response = client.post(
        "/api/live-sessions",
        json={
            "project_id": project_id,
            "name": "live workcell scan",
            "category": "workcell",
            "mass_kg": 3.2,
            "friction": 0.7,
        },
    )
    assert create_response.status_code == 201
    session = create_response.json()
    assert session["status"] == "recording"

    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(40, 80, 120)).save(image_buffer, format="JPEG")
    image_buffer.seek(0)
    depth_buffer = io.BytesIO()
    np.save(depth_buffer, np.array([[1.0, 1.1], [1.2, 1.3]], dtype=np.float32))
    depth_buffer.seek(0)

    frame_response = client.post(
        f"/api/live-sessions/{session['id']}/frames",
        data={
            "frame_id": "frame_000001",
            "timestamp": "1.25",
            "tracking_state": "normal",
            "transform": json.dumps([1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]),
            "intrinsics": json.dumps({"width": 2, "height": 2, "fx": 2.0, "fy": 2.0, "cx": 0.5, "cy": 0.5, "depth_scale": 1.0}),
        },
        files={
            "image": ("frame_000001.jpg", image_buffer, "image/jpeg"),
            "depth": ("frame_000001.npy", depth_buffer, "application/octet-stream"),
        },
    )

    assert frame_response.status_code == 200
    streamed = frame_response.json()
    assert streamed["frame_count"] == 1
    assert streamed["depth_frame_count"] == 1
    assert streamed["latest_frame_id"] == "frame_000001"
    assert streamed["scene"]["source_kind"] == "live_rgbd_depth_bounds"
    live_object = streamed["scene"]["objects"][0]
    assert live_object["id"] == "live_scene_001"
    assert live_object["category"] == "workcell"
    assert live_object["dimensions"][0] > 0
    assert live_object["dimensions"][1] > 0
    assert live_object["dimensions"][2] > 0

    fetched = client.get(f"/api/live-sessions/{session['id']}").json()
    assert fetched["scene"]["objects"][0]["pose"]["position"] == live_object["pose"]["position"]

    finalize_response = client.post(f"/api/live-sessions/{session['id']}/finalize")
    assert finalize_response.status_code == 201
    finalized = finalize_response.json()
    assert finalized["session"]["status"] == "finalized"
    assert finalized["task"]["status"] == "queued"
    stored_input = Path(client.app.state.db.get_task(finalized["task"]["id"])["input_path"])
    assert stored_input.name == "live_capture.zip"
    with zipfile.ZipFile(stored_input) as archive:
        names = set(archive.namelist())
    assert {"capture_manifest.json", "intrinsics.json", "poses.json", "images/frame_000001.jpg", "depth/frame_000001.npy"}.issubset(names)


def test_health_reports_real_dependency_status(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["storage"]["data_dir"].endswith("/data")
    assert payload["storage"]["output_dir"].endswith("/outputs")
    assert {"colmap", "InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "TextureMesh", "blender", "ffmpeg", "python:mujoco"}.issubset(
        payload["dependencies"].keys()
    )
    for dependency in payload["dependencies"].values():
        assert set(dependency) >= {"name", "available", "path", "version"}


def test_mesh_upload_run_produces_complete_simulation_package(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    mesh_path = tmp_path / "box.obj"
    write_box_obj(mesh_path)

    with mesh_path.open("rb") as mesh_file:
        create_response = client.post(
            "/api/tasks",
            data={
                "project_id": project_id,
                "name": "box asset",
                "mode": "asset",
                "category": "box",
                "material_category": "corrugated_cardboard",
                "mass_kg": "1.2",
                "friction": "0.7",
            },
            files={"capture": ("box.obj", mesh_file, "model/obj")},
        )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    run_response = client.post(f"/api/tasks/{task_id}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    assert task["status"] == "completed"
    assert task["report"]["valid"] is True
    assert task["report"]["source_kind"] == "mesh"
    assert task["report"]["mesh"]["visual_faces"] == 12
    assert task["report"]["mesh"]["collision_faces"] > 0
    assert task["report"]["physics"]["mass_kg"] == 1.2
    assert task["report"]["physics"]["material_category"] == "corrugated_cardboard"
    assert task["report"]["physics"]["material_category_source"] == "provided"
    assert task["material_category"] == "corrugated_cardboard"
    assert task["scene"]["objects"][0]["material_category"] == "corrugated_cardboard"
    assert task["scene"]["objects"][0]["material_category_source"] == "provided"
    assert task["report"]["simulator_validation"]["mjcf"]["xml_parse_valid"] is True
    assert task["report"]["simulator_validation"]["mjcf"]["mujoco_load_valid"] is True
    assert task["report"]["simulator_validation"]["mjcf"]["step_valid"] is True

    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    expected = {
        "assets/box_asset_visual.obj",
        "assets/box_asset_visual.glb",
        "assets/box_asset_collision.obj",
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
    assert expected.issubset(artifacts)

    zip_url = next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "real2sim_package.zip")
    zip_response = client.get(zip_url)
    assert zip_response.status_code == 200
    package_path = tmp_path / "downloaded.zip"
    package_path.write_bytes(zip_response.content)
    with zipfile.ZipFile(package_path) as archive:
        assert expected - {"real2sim_package.zip"} <= set(archive.namelist())

    manifest = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "manifest.json")).json()
    assert manifest["assets"][0]["material_category"] == "corrugated_cardboard"
    asset = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "asset.json")).json()
    assert asset["material_category"] == "corrugated_cardboard"


def test_mesh_upload_uses_real_coacd_collision_decomposition_parts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    mesh_path = tmp_path / "two_boxes.obj"
    write_two_box_obj(mesh_path)

    with mesh_path.open("rb") as mesh_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "two box asset", "mode": "asset", "category": "fixture"},
            files={"capture": ("two_boxes.obj", mesh_file, "model/obj")},
        )
    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    metrics = task["report"]["mesh"]
    assert metrics["collision_backend"] == "coacd"
    assert metrics["collision_part_count"] >= 2
    collision_meshes = task["scene"]["objects"][0]["collision_meshes"]
    assert len(collision_meshes) == metrics["collision_part_count"]
    assert all(path.startswith("assets/two_box_asset_collision_part_") for path in collision_meshes)
    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    assert set(collision_meshes).issubset(artifacts)
    manifest = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "manifest.json")).json()
    assert manifest["assets"][0]["collision_meshes"] == collision_meshes
    scene_xml = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "scene.xml")).text
    assert "two_box_asset_collision_001" in scene_xml
    assert "two_box_asset_collision_002" in scene_xml


def test_mesh_upload_removes_small_floating_components_before_export(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    mesh_path = tmp_path / "box_with_floater.obj"
    write_box_with_small_floater_obj(mesh_path)

    with mesh_path.open("rb") as mesh_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "cleaned box", "mode": "asset", "category": "box"},
            files={"capture": ("box_with_floater.obj", mesh_file, "model/obj")},
        )
    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    cleanup = task["report"]["mesh_cleanup"]
    assert cleanup["components_before"] == 2
    assert cleanup["components_after"] == 1
    assert cleanup["removed_component_count"] == 1
    assert cleanup["removed_face_count"] == 12
    assert task["report"]["mesh"]["visual_faces"] == 12

    visual_obj = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "assets/cleaned_box_visual.obj")).text
    assert "10 10 10" not in visual_obj


def test_textured_mesh_package_preserves_real_texture_files(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    texture = Image.new("RGB", (8, 8), color=(40, 120, 220))
    texture_path = tmp_path / "albedo.png"
    texture.save(texture_path)
    obj_path = tmp_path / "textured.obj"
    obj_path.write_text(
        "\n".join(
            [
                "mtllib materials.mtl",
                "usemtl painted",
                "v -0.5 -0.5 0.0",
                "v 0.5 -0.5 0.0",
                "v 0.5 0.5 0.0",
                "v -0.5 0.5 0.0",
                "v -0.5 -0.5 1.0",
                "v 0.5 -0.5 1.0",
                "v 0.5 0.5 1.0",
                "v -0.5 0.5 1.0",
                "vt 0 0",
                "vt 1 0",
                "vt 1 1",
                "vt 0 1",
                "f 1/1 2/2 3/3",
                "f 1/1 3/3 4/4",
                "f 5/1 8/4 7/3",
                "f 5/1 7/3 6/2",
                "f 1/1 5/2 6/3",
                "f 1/1 6/3 2/4",
                "f 2/1 6/2 7/3",
                "f 2/1 7/3 3/4",
                "f 3/1 7/2 8/3",
                "f 3/1 8/3 4/4",
                "f 4/1 8/2 5/3",
                "f 4/1 5/3 1/4",
            ]
        ),
        encoding="utf-8",
    )
    mtl_path = tmp_path / "materials.mtl"
    mtl_path.write_text("newmtl painted\nKd 1 1 1\nmap_Kd textures/albedo.png\n", encoding="utf-8")
    capture_zip = tmp_path / "textured.zip"
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(obj_path, "model/textured.obj")
        archive.write(mtl_path, "model/materials.mtl")
        archive.write(texture_path, "model/textures/albedo.png")

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "textured bottle", "mode": "asset", "category": "bottle"},
            files={"capture": ("textured.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    texture_artifact = "textures/textured_bottle_albedo.png"
    assert task["report"]["quality"]["textures_present"] is True
    assert task["scene"]["objects"][0]["texture_files"] == [texture_artifact]
    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    assert texture_artifact in artifacts
    manifest = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "manifest.json")).json()
    assert manifest["assets"][0]["texture_files"] == [texture_artifact]

    verify_response = client.post(f"/api/tasks/{task['id']}/verify-simulation")
    assert verify_response.status_code == 200
    validation = verify_response.json()["report"]["package_validation"]
    assert validation["artifact_completeness"]["texture_file_count"] == 1
    assert validation["manifest"]["missing_texture_references"] == []


def test_image_capture_without_reconstruction_tools_fails_explicitly(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        {
            "photogrammetry_required_tools": ["definitely-missing-colmap-for-test"],
            "capture_min_frames": 1,
            "capture_min_usable_frames": 1,
        },
    )
    project_id = create_project(client)
    capture_zip = tmp_path / "images.zip"
    image_path = tmp_path / "frame_001.png"
    write_checker_image(image_path)
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(image_path, "images/frame_001.png")

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "image scan", "mode": "asset", "category": "bottle"},
            files={"capture": ("images.zip", capture_file, "application/zip")},
        )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    run_response = client.post(f"/api/tasks/{task_id}/run")

    assert run_response.status_code == 409
    task = run_response.json()
    assert task["status"] == "failed"
    assert task["failure_reason"] == "missing_reconstruction_dependencies"
    assert task["report"]["capture_quality"]["valid"] is True
    assert "definitely-missing-colmap-for-test" in "\n".join(task["logs"])
    assert task["artifacts"] == []


def test_capture_quality_detects_blur_exposure_and_scale_metadata(tmp_path: Path) -> None:
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'unused.sqlite3'}")
    capture_dir = tmp_path / "capture"
    images_dir = tmp_path / "images"
    capture_dir.mkdir()
    images_dir.mkdir()
    sharp = images_dir / "sharp.png"
    blurred = images_dir / "blurred.png"
    dark = images_dir / "dark.png"
    write_checker_image(sharp)
    Image.open(sharp).filter(ImageFilter.GaussianBlur(radius=8)).save(blurred)
    Image.new("RGB", (96, 96), color=(0, 0, 0)).save(dark)
    (capture_dir / "scale.json").write_text('{"unit":"meter","marker_length_m":0.1}', encoding="utf-8")
    (capture_dir / "poses.json").write_text(
        json.dumps(
            {
                "frames": [
                    {"position": [1.0, 0.0, 0.0], "tracking_state": "normal"},
                    {"position": [0.0, 1.0, 0.0], "tracking_state": "limited"},
                    {"position": [-1.0, 0.0, 0.0], "tracking_state": "normal"},
                ]
            }
        ),
        encoding="utf-8",
    )

    quality = analyze_capture_quality(images_dir, capture_dir, settings)

    assert quality["frame_count"] == 3
    assert quality["usable_frame_count"] == 1
    assert quality["blurry_frame_count"] >= 1
    assert quality["underexposed_frame_count"] == 1
    assert quality["has_scale_reference"] is True
    assert quality["tracking_lost_events"] == 1
    assert quality["coverage_angle_degrees"] >= 170
    assert quality["valid"] is False
    assert "too_few_usable_frames" in quality["issues"]


def test_bad_capture_fails_before_reconstruction_and_persists_quality_report(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        {
            "photogrammetry_required_tools": [],
            "capture_min_usable_frames": 2,
        },
    )
    project_id = create_project(client)
    dark_image = tmp_path / "dark.png"
    Image.new("RGB", (64, 64), color=(0, 0, 0)).save(dark_image)
    capture_zip = tmp_path / "bad-capture.zip"
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(dark_image, "images/dark.png")

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "bad capture", "mode": "asset", "category": "bottle"},
            files={"capture": ("bad-capture.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 409
    task = run_response.json()
    assert task["failure_reason"] == "capture_quality_failed"
    assert task["report"]["capture_quality"]["valid"] is False
    assert "too_few_usable_frames" in task["report"]["capture_quality"]["issues"]
    assert "underexposed_frame_count" in task["report"]["capture_quality"]


def test_kiri_provider_without_api_key_fails_explicitly_after_quality_gate(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        {
            "reconstruction_provider": "kiri_featureless",
            "capture_min_frames": 1,
            "capture_min_usable_frames": 1,
        },
    )
    project_id = create_project(client)
    image_path = tmp_path / "frame_001.png"
    write_checker_image(image_path)
    capture_zip = tmp_path / "kiri-capture.zip"
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(image_path, "images/frame_001.png")

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "kiri fallback", "mode": "asset", "category": "shiny"},
            files={"capture": ("kiri-capture.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 409
    task = run_response.json()
    assert task["failure_reason"] == "kiri_api_key_required"
    assert task["report"]["capture_quality"]["valid"] is True


def test_apple_object_capture_without_command_fails_explicitly_after_quality_gate(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        {
            "reconstruction_provider": "apple_object_capture",
            "apple_object_capture_command": None,
            "capture_min_frames": 1,
            "capture_min_usable_frames": 1,
        },
    )
    project_id = create_project(client)
    image_path = tmp_path / "frame_001.png"
    write_checker_image(image_path)
    capture_zip = tmp_path / "apple-capture.zip"
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(image_path, "images/frame_001.png")

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "apple fallback", "mode": "asset", "category": "object"},
            files={"capture": ("apple-capture.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 409
    task = run_response.json()
    assert task["failure_reason"] == "apple_object_capture_command_required"
    assert task["report"]["capture_quality"]["valid"] is True


def test_scene_object_patch_regenerates_manifest_and_exports(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    mesh_path = tmp_path / "box.obj"
    write_box_obj(mesh_path)
    with mesh_path.open("rb") as mesh_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "editable box", "mode": "asset", "category": "box"},
            files={"capture": ("box.obj", mesh_file, "model/obj")},
        )
    task_id = create_response.json()["id"]
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    patch_response = client.patch(
        f"/api/tasks/{task_id}/scene/objects/asset_001",
        json={
            "name": "calibrated crate",
            "category": "crate",
            "material_category": "wood_composite",
            "mass_kg": 2.5,
            "friction": 0.55,
        },
    )

    assert patch_response.status_code == 200
    task = patch_response.json()
    assert task["scene"]["objects"][0]["name"] == "calibrated crate"
    assert task["scene"]["objects"][0]["category"] == "crate"
    assert task["scene"]["objects"][0]["material_category"] == "wood_composite"
    assert task["scene"]["objects"][0]["material_category_source"] == "provided"
    assert task["scene"]["objects"][0]["mass_kg"] == 2.5

    manifest_url = next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "manifest.json")
    manifest = client.get(manifest_url).json()
    assert manifest["assets"][0]["category"] == "crate"
    assert manifest["assets"][0]["material_category"] == "wood_composite"
    assert manifest["assets"][0]["material_category_source"] == "provided"
    assert manifest["assets"][0]["mass_kg"] == 2.5

    asset_url = next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "asset.json")
    asset = client.get(asset_url).json()
    assert asset["material_category"] == "wood_composite"

    xml_url = next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "scene.xml")
    assert "calibrated_crate" in client.get(xml_url).text


def test_roomplan_scene_package_generates_metric_scene_and_assets(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    capture_zip = tmp_path / "roomplan.zip"
    roomplan = {
        "unit": "meter",
        "up_axis": "z",
        "surfaces": [
            {
                "id": "floor_001",
                "name": "floor",
                "category": "floor",
                "material_category": "sealed_concrete",
                "dimensions": [3.0, 2.0, 0.05],
                "pose": {"position": [0.0, 0.0, -0.025], "quaternion": [1.0, 0.0, 0.0, 0.0]},
            },
            {
                "id": "wall_001",
                "name": "back wall",
                "category": "wall",
                "dimensions": [3.0, 0.05, 2.4],
                "pose": {"position": [0.0, -1.0, 1.2], "quaternion": [1.0, 0.0, 0.0, 0.0]},
            },
        ],
        "objects": [
            {
                "id": "table_001",
                "name": "work table",
                "category": "table",
                "material_category": "laminated_wood",
                "dimensions": [1.2, 0.8, 0.75],
                "pose": {"position": [0.0, 0.0, 0.375], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "mass_kg": 18.0,
                "friction": 0.8,
            },
            {
                "id": "bottle_001",
                "name": "bottle",
                "category": "bottle",
                "material_category": "polyethylene_plastic",
                "dimensions": [0.08, 0.08, 0.24],
                "pose": {"position": [0.2, 0.1, 0.87], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "mass_kg": 0.12,
                "friction": 0.55,
            },
        ],
    }
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.writestr("roomplan.json", json.dumps(roomplan))
        archive.writestr("roomplan.usd", "#usda 1.0\n")

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "room corner", "mode": "scene", "category": "room"},
            files={"capture": ("roomplan.zip", capture_file, "application/zip")},
        )
    task_id = create_response.json()["id"]

    run_response = client.post(f"/api/tasks/{task_id}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    assert task["status"] == "completed"
    assert task["report"]["source_kind"] == "roomplan"
    assert task["report"]["scene"]["object_count"] == 2
    assert task["report"]["scene"]["static_geometry_count"] == 2
    assert task["scene"]["static_geometry"][0]["category"] == "floor"
    assert task["scene"]["static_geometry"][0]["material_category"] == "sealed_concrete"
    assert [obj["id"] for obj in task["scene"]["objects"]] == ["table_001", "bottle_001"]
    assert task["scene"]["objects"][0]["material_category"] == "laminated_wood"
    assert task["scene"]["objects"][1]["material_category"] == "polyethylene_plastic"

    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    assert "assets/table_001_visual.obj" in artifacts
    assert "assets/bottle_001_collision.obj" in artifacts
    manifest = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "manifest.json")).json()
    assert {asset["id"] for asset in manifest["assets"]} == {"table_001", "bottle_001"}
    assert {asset["material_category"] for asset in manifest["assets"]} == {"laminated_wood", "polyethylene_plastic"}
    assert manifest["static_geometry"][0]["material_category"] == "sealed_concrete"
    assert task["report"]["simulator_validation"]["mjcf"]["step_valid"] is True


def test_roomplan_scene_package_preserves_uploaded_residual_scene_mesh(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    capture_zip = tmp_path / "roomplan-with-scene-mesh.zip"
    scene_mesh = tmp_path / "scene_mesh.obj"
    write_box_obj(scene_mesh)
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
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.writestr("roomplan.json", json.dumps(roomplan))
        archive.write(scene_mesh, "scene_mesh.obj")

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "room with residual mesh", "mode": "scene", "category": "room"},
            files={"capture": ("roomplan-with-scene-mesh.zip", capture_file, "application/zip")},
        )
    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    assert task["report"]["scene"]["residual_scene_mesh_count"] == 1
    residual = next(entry for entry in task["scene"]["static_geometry"] if entry["id"] == "scene_mesh")
    assert residual["category"] == "residual_scene"
    assert residual["source"]["kind"] == "roomplan_scene_mesh"
    assert residual["visual_mesh"] == "assets/scene_mesh_visual.obj"
    assert residual["visual_glb"] == "assets/scene_mesh_visual.glb"
    assert residual["collision_mesh"] == "assets/scene_mesh_collision.obj"
    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    assert {"assets/scene_mesh_visual.obj", "assets/scene_mesh_visual.glb", "assets/scene_mesh_collision.obj"}.issubset(artifacts)
    manifest = client.get(next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "manifest.json")).json()
    manifest_residual = next(entry for entry in manifest["static_geometry"] if entry["id"] == "scene_mesh")
    assert manifest_residual["visual_mesh"] == "assets/scene_mesh_visual.obj"
    assert task["report"]["simulator_validation"]["mjcf"]["step_valid"] is True


def test_roomplan_scene_package_validation_reports_support_contacts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    task_id = create_roomplan_task(client, tmp_path, project_id)
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    verify_response = client.post(f"/api/tasks/{task_id}/verify-simulation")

    assert verify_response.status_code == 200
    validation = verify_response.json()["report"]["package_validation"]
    contacts = validation["contact_relationships"]
    assert contacts["valid"] is True
    assert contacts["unsupported_objects"] == []
    relation_by_object = {relation["object_id"]: relation for relation in contacts["support_relations"]}
    assert relation_by_object["table_001"]["support_id"] == "floor_001"
    assert relation_by_object["bottle_001"]["support_id"] == "table_001"


def test_roomplan_scene_package_validation_fails_for_unsupported_object(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    task_id = create_roomplan_task(client, tmp_path, project_id, bottle_center_z=1.3)
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    verify_response = client.post(f"/api/tasks/{task_id}/verify-simulation")

    assert verify_response.status_code == 200
    validation = verify_response.json()["report"]["package_validation"]
    assert validation["valid"] is False
    contacts = validation["contact_relationships"]
    assert contacts["valid"] is False
    assert contacts["unsupported_objects"] == ["bottle_001"]


def test_rgbd_mask_scene_package_lifts_masks_to_metric_objects(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    capture_zip = tmp_path / "rgbd-scene.zip"
    mask = Image.new("L", (4, 4), color=0)
    for y in [1, 2]:
        for x in [1, 2]:
            mask.putpixel((x, y), 255)
    mask_path = tmp_path / "bottle_001.png"
    mask.save(mask_path)
    depth = [[0.0, 0.0, 0.0, 0.0], [0.0, 1.0, 1.0, 0.0], [0.0, 1.0, 1.0, 0.0], [0.0, 0.0, 0.0, 0.0]]
    depth_path = tmp_path / "bottle_001.npy"
    import numpy as np

    np.save(depth_path, np.array(depth, dtype=np.float32))
    intrinsics = {"width": 4, "height": 4, "fx": 2.0, "fy": 2.0, "cx": 1.5, "cy": 1.5, "depth_scale": 1.0}
    metadata = {"bottle_001": {"name": "lifted bottle", "category": "bottle", "mass_kg": 0.2, "friction": 0.5}}
    poses = {"frames": [{"id": "bottle_001", "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0.1, 0.2, 0.3, 1]}]}
    surfaces = [
        {
            "id": "floor_001",
            "name": "floor",
            "category": "floor",
            "dimensions": [3.0, 2.0, 0.05],
            "pose": {"position": [0, 0, -0.025], "quaternion": [1, 0, 0, 0]},
        }
    ]
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(mask_path, "masks/bottle_001.png")
        archive.write(depth_path, "depth/bottle_001.npy")
        archive.writestr("intrinsics.json", json.dumps(intrinsics))
        archive.writestr("objects.json", json.dumps(metadata))
        archive.writestr("poses.json", json.dumps(poses))
        archive.writestr("surfaces.json", json.dumps(surfaces))

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "rgbd tabletop", "mode": "scene", "category": "scene"},
            files={"capture": ("rgbd-scene.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    assert task["report"]["source_kind"] == "rgbd_lifting"
    assert task["report"]["segmentation"]["object_count"] == 1
    obj = task["scene"]["objects"][0]
    assert obj["id"] == "bottle_001"
    assert obj["name"] == "lifted bottle"
    assert obj["category"] == "bottle"
    assert obj["dimensions"] == [0.5, 0.5, 0.001]
    assert obj["pose"]["position"] == [0.1, 0.2, 1.3]
    assert task["scene"]["static_geometry"][0]["category"] == "floor"
    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    assert "assets/bottle_001_visual.obj" in artifacts
    visual_obj_url = next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "assets/bottle_001_visual.obj")
    visual_obj = client.get(visual_obj_url).text
    assert sum(1 for line in visual_obj.splitlines() if line.startswith("v ")) == 4
    assert sum(1 for line in visual_obj.splitlines() if line.startswith("f ")) == 2
    assert task["report"]["simulator_validation"]["mjcf"]["step_valid"] is True


def test_rgbd_scene_without_masks_clusters_depth_into_metric_objects(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    capture_zip = tmp_path / "rgbd-clusters.zip"
    import numpy as np

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
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(depth_path, "depth/frame_001.npy")
        archive.writestr("intrinsics.json", json.dumps(intrinsics))
        archive.writestr("surfaces.json", json.dumps(surfaces))

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "unmasked rgbd tabletop", "mode": "scene", "category": "object"},
            files={"capture": ("rgbd-clusters.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    assert task["report"]["source_kind"] == "rgbd_clustering"
    assert task["report"]["segmentation"]["provider"] == "rgbd_depth_clustering"
    assert task["report"]["segmentation"]["object_count"] == 2
    assert [obj["id"] for obj in task["scene"]["objects"]] == ["cluster_001", "cluster_002"]
    assert all(obj["source"]["kind"] == "rgbd_depth_cluster" for obj in task["scene"]["objects"])
    assert task["scene"]["static_geometry"][0]["category"] == "table"
    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    assert "assets/cluster_001_visual.obj" in artifacts
    assert "assets/cluster_002_collision.obj" in artifacts
    visual_obj_url = next(artifact["url"] for artifact in task["artifacts"] if artifact["path"] == "assets/cluster_001_visual.obj")
    visual_obj = client.get(visual_obj_url).text
    assert sum(1 for line in visual_obj.splitlines() if line.startswith("v ")) == 4
    assert sum(1 for line in visual_obj.splitlines() if line.startswith("f ")) == 2
    assert task["report"]["simulator_validation"]["mjcf"]["step_valid"] is True

    verify_response = client.post(f"/api/tasks/{task['id']}/verify-simulation")
    assert verify_response.status_code == 200
    contacts = verify_response.json()["report"]["package_validation"]["contact_relationships"]
    assert contacts["valid"] is True
    assert {relation["support_id"] for relation in contacts["support_relations"]} == {"table_001"}


def test_scene_resegment_reruns_real_rgbd_capture_and_regenerates_exports(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    capture_zip = tmp_path / "initial-rgbd.zip"
    write_rgbd_capture_zip(capture_zip, ["bottle_001"])
    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "resegment tabletop", "mode": "scene", "category": "object"},
            files={"capture": ("rgbd-scene.zip", capture_file, "application/zip")},
        )
    task_id = create_response.json()["id"]
    run_response = client.post(f"/api/tasks/{task_id}/run")
    assert run_response.status_code == 200
    assert [obj["id"] for obj in run_response.json()["scene"]["objects"]] == ["bottle_001"]

    stored_input = Path(client.app.state.db.get_task(task_id)["input_path"])
    write_rgbd_capture_zip(stored_input, ["cup_001", "book_001"])

    resegment_response = client.post(f"/api/tasks/{task_id}/scene/resegment")

    assert resegment_response.status_code == 200
    task = resegment_response.json()
    assert [obj["id"] for obj in task["scene"]["objects"]] == ["book_001", "cup_001"]
    assert task["report"]["last_resegment"]["valid"] is True
    assert task["report"]["segmentation"]["object_count"] == 2
    artifacts = {artifact["path"] for artifact in task["artifacts"]}
    assert "assets/book_001_visual.obj" in artifacts
    assert "assets/cup_001_collision.obj" in artifacts
    assert any("scene resegmented and exports regenerated" in log for log in task["logs"])


def test_sam2_provider_runs_real_command_and_lifts_generated_masks(tmp_path: Path) -> None:
    runner_script = tmp_path / "sam2_runner.py"
    runner_script.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "from PIL import Image",
                "import sys",
                "out = Path(sys.argv[1])",
                "out.mkdir(parents=True, exist_ok=True)",
                "mask = Image.new('L', (4, 4), color=0)",
                "for y in [1, 2]:",
                "    for x in [1, 2]:",
                "        mask.putpixel((x, y), 255)",
                "mask.save(out / 'bottle_001.png')",
            ]
        ),
        encoding="utf-8",
    )
    client = make_client(
        tmp_path,
        {
            "segmentation_provider": "sam2",
            "sam2_command": f'"{sys.executable}" "{runner_script}" "{{output_masks_dir}}"',
        },
    )
    project_id = create_project(client)
    capture_zip = tmp_path / "sam2-rgbd.zip"
    image_path = tmp_path / "frame_001.png"
    write_checker_image(image_path)
    import numpy as np

    depth_path = tmp_path / "bottle_001.npy"
    np.save(depth_path, np.array([[0, 0, 0, 0], [0, 1, 1, 0], [0, 1, 1, 0], [0, 0, 0, 0]], dtype=np.float32))
    intrinsics = {"width": 4, "height": 4, "fx": 2.0, "fy": 2.0, "cx": 1.5, "cy": 1.5, "depth_scale": 1.0}
    metadata = {"bottle_001": {"name": "sam2 bottle", "category": "bottle", "mass_kg": 0.2, "friction": 0.5}}
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(image_path, "images/frame_001.png")
        archive.write(depth_path, "depth/bottle_001.npy")
        archive.writestr("intrinsics.json", json.dumps(intrinsics))
        archive.writestr("objects.json", json.dumps(metadata))

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "sam2 tabletop", "mode": "scene", "category": "scene"},
            files={"capture": ("sam2-rgbd.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    assert task["report"]["source_kind"] == "rgbd_lifting"
    assert task["report"]["segmentation"]["provider"] == "sam2"
    assert task["report"]["segmentation"]["mask_count"] == 1
    assert task["scene"]["objects"][0]["name"] == "sam2 bottle"
    assert task["scene"]["objects"][0]["dimensions"] == [0.5, 0.5, 0.001]
    assert any("SAM2 segmentation generated 1 mask" in log for log in task["logs"])


def test_sam2_provider_fails_when_runner_produces_no_masks(tmp_path: Path) -> None:
    runner_script = tmp_path / "empty_sam2_runner.py"
    runner_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    client = make_client(
        tmp_path,
        {
            "segmentation_provider": "sam2",
            "sam2_command": f'"{sys.executable}" "{runner_script}" "{{output_masks_dir}}"',
        },
    )
    project_id = create_project(client)
    capture_zip = tmp_path / "empty-sam2.zip"
    image_path = tmp_path / "frame_001.png"
    write_checker_image(image_path)
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(image_path, "images/frame_001.png")
        archive.writestr("intrinsics.json", json.dumps({"fx": 2.0, "fy": 2.0, "cx": 1.5, "cy": 1.5}))

    with capture_zip.open("rb") as capture_file:
        create_response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "empty sam2", "mode": "scene", "category": "scene"},
            files={"capture": ("empty-sam2.zip", capture_file, "application/zip")},
        )

    run_response = client.post(f"/api/tasks/{create_response.json()['id']}/run")

    assert run_response.status_code == 409
    task = run_response.json()
    assert task["failure_reason"] == "sam2_masks_missing"
    assert task["report"]["segmentation"]["provider"] == "sam2"
    assert task["report"]["segmentation"]["valid"] is False


def test_scene_object_delete_split_and_merge_regenerate_exports(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    task_id = create_roomplan_task(client, tmp_path, project_id)
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    delete_response = client.delete(f"/api/tasks/{task_id}/scene/objects/bottle_001")
    assert delete_response.status_code == 200
    deleted_task = delete_response.json()
    assert [obj["id"] for obj in deleted_task["scene"]["objects"]] == ["table_001"]
    manifest = client.get(next(artifact["url"] for artifact in deleted_task["artifacts"] if artifact["path"] == "manifest.json")).json()
    assert [asset["id"] for asset in manifest["assets"]] == ["table_001"]
    assert "bottle_001" not in client.get(next(artifact["url"] for artifact in deleted_task["artifacts"] if artifact["path"] == "scene.xml")).text

    split_response = client.post(
        f"/api/tasks/{task_id}/scene/objects/table_001/split",
        json={"axis": "x", "left_name": "left table half", "right_name": "right table half"},
    )
    assert split_response.status_code == 200
    split_task = split_response.json()
    split_ids = [obj["id"] for obj in split_task["scene"]["objects"]]
    assert split_ids == ["table_001_a", "table_001_b"]
    assert split_task["scene"]["objects"][0]["dimensions"][0] == 0.6
    assert split_task["scene"]["objects"][1]["dimensions"][0] == 0.6
    split_artifacts = {artifact["path"] for artifact in split_task["artifacts"]}
    assert "assets/table_001_a_visual.obj" in split_artifacts
    assert "assets/table_001_b_collision.obj" in split_artifacts

    merge_response = client.post(
        f"/api/tasks/{task_id}/scene/objects/merge",
        json={"object_ids": ["table_001_a", "table_001_b"], "name": "merged table", "category": "table"},
    )
    assert merge_response.status_code == 200
    merged_task = merge_response.json()
    assert [obj["id"] for obj in merged_task["scene"]["objects"]] == ["merged_table"]
    merged = merged_task["scene"]["objects"][0]
    assert merged["dimensions"][0] == 1.2
    assert merged["category"] == "table"
    assert merged_task["report"]["simulator_validation"]["mjcf"]["mujoco_load_valid"] is True
    assert merged_task["report"]["simulator_validation"]["mjcf"]["step_valid"] is True


def test_scene_object_can_be_exported_as_standalone_asset_package(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    task_id = create_roomplan_task(client, tmp_path, project_id)
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    export_response = client.post(f"/api/tasks/{task_id}/scene/objects/bottle_001/export")

    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"
    package_path = tmp_path / "bottle_export.zip"
    package_path.write_bytes(export_response.content)
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        assert {
            "assets/bottle_001_visual.obj",
            "assets/bottle_001_visual.glb",
            "assets/bottle_001_collision.obj",
            "manifest.json",
            "asset.json",
            "scene.json",
            "scene.xml",
            "scene.urdf",
            "scene.usd",
            "scene.usdz",
            "report.json",
            "README.md",
        }.issubset(names)
        assert not any(name.startswith("assets/table_001") for name in names)
        assert not any(name.startswith("assets/floor_001") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        scene = json.loads(archive.read("scene.json"))
        report = json.loads(archive.read("report.json"))

    assert [asset["id"] for asset in manifest["assets"]] == ["bottle_001"]
    assert [obj["id"] for obj in scene["objects"]] == ["bottle_001"]
    assert scene["objects"][0]["pose"]["position"] == [0.0, 0.0, 0.12]
    assert report["source_kind"] == "standalone_scene_object"
    assert report["simulator_validation"]["mjcf"]["mujoco_load_valid"] is True
    assert report["simulator_validation"]["mjcf"]["step_valid"] is True


def test_video_capture_zip_extracts_real_frames_with_ffmpeg(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise AssertionError("ffmpeg is required for real video frame extraction")

    video_path = tmp_path / "scan.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=2",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    capture_zip = tmp_path / "video_capture.zip"
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.write(video_path, "video/scan.mp4")

    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'unused.sqlite3'}",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
    )
    logs: list[str] = []
    images_dir = extract_capture_media(capture_zip, tmp_path / "work", settings, logs)

    extracted = sorted(images_dir.glob("*.jpg"))
    assert extracted
    assert "ffmpeg" in "\n".join(logs)


def create_roomplan_task(client: TestClient, tmp_path: Path, project_id: str, bottle_center_z: float = 0.87) -> str:
    capture_zip = tmp_path / f"roomplan-{project_id}.zip"
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
                "id": "table_001",
                "name": "work table",
                "category": "table",
                "dimensions": [1.2, 0.8, 0.75],
                "pose": {"position": [0.0, 0.0, 0.375], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "mass_kg": 18.0,
                "friction": 0.8,
            },
            {
                "id": "bottle_001",
                "name": "bottle",
                "category": "bottle",
                "dimensions": [0.08, 0.08, 0.24],
                "pose": {"position": [0.2, 0.1, bottle_center_z], "quaternion": [1.0, 0.0, 0.0, 0.0]},
                "mass_kg": 0.12,
                "friction": 0.55,
            },
        ],
    }
    with zipfile.ZipFile(capture_zip, "w") as archive:
        archive.writestr("roomplan.json", json.dumps(roomplan))

    with capture_zip.open("rb") as capture_file:
        response = client.post(
            "/api/tasks",
            data={"project_id": project_id, "name": "qa room", "mode": "scene", "category": "room"},
            files={"capture": ("roomplan.zip", capture_file, "application/zip")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def write_checker_image(path: Path) -> None:
    image = Image.new("RGB", (96, 96), color=(240, 240, 240))
    pixels = image.load()
    for y in range(96):
        for x in range(96):
            if (x // 8 + y // 8) % 2 == 0:
                pixels[x, y] = (20, 20, 20)
    image.save(path)


def write_rgbd_capture_zip(path: Path, object_ids: list[str]) -> None:
    import numpy as np

    metadata = {
        object_id: {"name": object_id.replace("_", " "), "category": "object", "mass_kg": 0.2, "friction": 0.5}
        for object_id in object_ids
    }
    intrinsics = {"width": 4, "height": 4, "fx": 2.0, "fy": 2.0, "cx": 1.5, "cy": 1.5, "depth_scale": 1.0}
    depth = np.array([[0, 0, 0, 0], [0, 1, 1, 0], [0, 1, 1, 0], [0, 0, 0, 0]], dtype=np.float32)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("intrinsics.json", json.dumps(intrinsics))
        archive.writestr("objects.json", json.dumps(metadata))
        for object_id in object_ids:
            mask = Image.new("L", (4, 4), color=0)
            for y in [1, 2]:
                for x in [1, 2]:
                    mask.putpixel((x, y), 255)
            mask_bytes = io.BytesIO()
            mask.save(mask_bytes, format="PNG")
            archive.writestr(f"masks/{object_id}.png", mask_bytes.getvalue())
            depth_bytes = io.BytesIO()
            np.save(depth_bytes, depth)
            archive.writestr(f"depth/{object_id}.npy", depth_bytes.getvalue())
