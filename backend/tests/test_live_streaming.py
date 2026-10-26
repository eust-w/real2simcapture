import io
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.rgbd_lifting import lift_depth_pixels
from app.settings import AppSettings


def make_session(tmp_path):
    app = create_app(AppSettings(database_url=f"sqlite:///{tmp_path}/db.sqlite", data_dir=tmp_path / "data", output_dir=tmp_path / "out"))
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Contract test"}).json()
    session = client.post("/api/live-sessions", json={"project_id": project["id"], "name": "Scan", "category": "scene"}).json()
    return client, session["id"]


TRIANGLE = b"v 0 0 0\nv 1 0 0\nv 0 1 1\nf 1 2 3\n"


def test_stream_mesh_is_downloadable_and_invalid_update_keeps_last_good_mesh(tmp_path):
    client, sid = make_session(tmp_path)
    endpoint = f"/api/live-sessions/{sid}/mesh"
    assert client.get(endpoint).status_code == 404
    response = client.post(endpoint, files={"mesh": ("scene.obj", TRIANGLE, "text/plain")})
    assert response.status_code == 200
    session = response.json()
    assert session["mesh_url"] == endpoint + "?version=1"
    assert session["scene"]["source_kind"] == "live_arkit_mesh"
    assert session["scene"]["metrics"]["face_count"] == 1
    download = client.get(session["mesh_url"])
    assert download.status_code == 200
    assert download.content == TRIANGLE
    assert download.headers["cache-control"] == "no-store"
    bad = client.post(endpoint, files={"mesh": ("bad.obj", b"<html>Forbidden</html>", "text/plain")})
    assert bad.status_code == 422
    assert client.get(endpoint).content == TRIANGLE
    assert client.get(f"/api/live-sessions/{sid}").json()["mesh_version"] == 1


def test_finalize_is_idempotent_and_preserves_real_mesh(tmp_path):
    client, sid = make_session(tmp_path)
    endpoint = f"/api/live-sessions/{sid}"
    client.post(endpoint + "/mesh", files={"mesh": ("scene.obj", TRIANGLE, "text/plain")})
    first = client.post(endpoint + "/finalize")
    second = client.post(endpoint + "/finalize")
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert client.get(endpoint + "/mesh").content == TRIANGLE
    assert client.post(endpoint + "/mesh", files={"mesh": ("scene.obj", TRIANGLE, "text/plain")}).status_code == 409


def test_concurrent_frame_uploads_are_not_lost_and_retry_does_not_duplicate(tmp_path):
    client, sid = make_session(tmp_path)
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="JPEG")

    def upload(index):
        return client.post(f"/api/live-sessions/{sid}/frames", data={"frame_id": f"frame_{index:06d}"}, files={"image": ("frame.jpg", image.getvalue(), "image/jpeg")}).status_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(upload, range(8))) == [200] * 8
    assert upload(0) == 200
    session = client.get(f"/api/live-sessions/{sid}").json()
    assert session["frame_count"] == 8
    poses = json.loads((tmp_path / "data" / "live_sessions" / sid / "poses.json").read_text())
    assert len({frame["id"] for frame in poses["frames"]}) == 8


def test_arkit_depth_uses_camera_forward_and_z_up_world():
    intrinsics = {"fx": 1, "fy": 1, "cx": 0, "cy": 0, "camera_convention": "arkit", "world_up_axis": "y"}
    transform = np.eye(4)
    transform[:3, 3] = [10, 20, 30]
    points, _, _ = lift_depth_pixels(np.array([[2.0]]), intrinsics, transform.T.flatten().tolist())
    # OpenCV depth -> ARKit camera (x,-y,-z) -> ARKit world -> z-up (x,-z,y).
    np.testing.assert_allclose(points, [[10, -28, 20]])


def test_invalid_frame_geometry_does_not_commit_partial_capture(tmp_path):
    client, sid = make_session(tmp_path)
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="JPEG")
    response = client.post(f"/api/live-sessions/{sid}/frames", data={"frame_id": "frame_1", "transform": "[1, 2]"}, files={"image": ("frame.jpg", image.getvalue(), "image/jpeg")})
    assert response.status_code == 422
    assert client.get(f"/api/live-sessions/{sid}").json()["frame_count"] == 0
    assert not list((tmp_path / "data" / "live_sessions" / sid / "images").iterdir())
