import sys
from importlib import util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.queue import enqueue_task, run_queued_once
from app.settings import AppSettings
from app.storage import LocalStorage, publish_artifacts_to_storage


def make_settings(tmp_path: Path, extra: dict | None = None) -> AppSettings:
    values = {
        "database_url": f"sqlite:///{tmp_path / 'real2sim.sqlite3'}",
        "data_dir": tmp_path / "data",
        "output_dir": tmp_path / "outputs",
        "public_base_url": "http://testserver",
    }
    values.update(extra or {})
    return AppSettings(**values)


def make_client(tmp_path: Path, extra: dict | None = None) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path, extra)))


def write_box_obj(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "v 0 0 0",
                "v 1 0 0",
                "v 1 1 0",
                "v 0 1 0",
                "v 0 0 1",
                "v 1 0 1",
                "v 1 1 1",
                "v 0 1 1",
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


def create_mesh_task(client: TestClient, tmp_path: Path) -> str:
    project = client.post("/api/projects", json={"name": "queue project"}).json()
    mesh_path = tmp_path / "box.obj"
    write_box_obj(mesh_path)
    with mesh_path.open("rb") as mesh_file:
        task = client.post(
            "/api/tasks",
            data={"project_id": project["id"], "name": "queued mesh", "mode": "asset", "category": "box"},
            files={"capture": ("box.obj", mesh_file, "model/obj")},
        ).json()
    return task["id"]


def test_local_storage_put_open_and_list_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(root=tmp_path / "object-store", public_base_url="http://testserver")
    source = tmp_path / "artifact.txt"
    source.write_text("real artifact", encoding="utf-8")

    stored = storage.put_file("tasks/task-001/artifact.txt", source)

    assert stored.key == "tasks/task-001/artifact.txt"
    assert stored.url == "/api/storage/tasks/task-001/artifact.txt"
    assert storage.open_file(stored.key).read_text(encoding="utf-8") == "real artifact"
    assert [item.key for item in storage.list_prefix("tasks/task-001")] == ["tasks/task-001/artifact.txt"]


def test_health_reports_queue_and_storage_backends(tmp_path: Path) -> None:
    client = make_client(tmp_path, {"queue_backend": "redis", "redis_url": "redis://127.0.0.1:1/0", "storage_backend": "local"})

    payload = client.get("/api/health").json()

    assert payload["queue"]["backend"] == "redis"
    assert payload["queue"]["available"] is False
    assert payload["queue"]["reason"] == "redis_unavailable"
    assert payload["storage_backend"]["backend"] == "local"
    assert payload["storage_backend"]["available"] is True


def test_health_reports_reconstruction_provider_readiness(tmp_path: Path) -> None:
    client = make_client(tmp_path, {"reconstruction_provider": "kiri_featureless"})

    payload = client.get("/api/health").json()

    assert payload["reconstruction"]["provider"] == "kiri_featureless"
    assert payload["reconstruction"]["providers"]["kiri_featureless"]["available"] is False
    assert payload["reconstruction"]["providers"]["kiri_featureless"]["reason"] == "kiri_api_key_required"
    assert payload["reconstruction"]["providers"]["apple_object_capture"]["available"] is True
    assert payload["reconstruction"]["providers"]["apple_object_capture"]["reason"] is None
    assert payload["reconstruction"]["providers"]["apple_object_capture"]["command"]
    assert payload["segmentation"]["provider"] == "rgbd_masks"
    assert payload["segmentation"]["providers"]["rgbd_masks"]["available"] is True
    assert payload["segmentation"]["providers"]["sam2"]["available"] is True
    assert payload["segmentation"]["providers"]["sam2"]["reason"] is None
    assert payload["segmentation"]["providers"]["sam2"]["command"]
    if AppSettings().motrixsim_validate_command:
        assert payload["simulators"]["providers"]["motrixsim"]["available"] is True
        assert payload["simulators"]["providers"]["motrixsim"]["reason"] is None
    else:
        assert payload["simulators"]["providers"]["motrixsim"]["available"] is False
        assert payload["simulators"]["providers"]["motrixsim"]["reason"] == "motrixsim_command_required"
    assert payload["simulators"]["providers"]["isaacsim"]["reason"] == "isaacsim_command_required"
    if util.find_spec("genesis") is None:
        assert payload["simulators"]["providers"]["genesis"]["reason"] == "genesis_command_required"
    else:
        assert payload["simulators"]["providers"]["genesis"]["available"] is True
        assert payload["simulators"]["providers"]["genesis"]["builtin"] is True


def test_enqueue_endpoint_keeps_task_queued_until_worker_consumes_it(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    task_id = create_mesh_task(client, tmp_path)

    response = client.post(f"/api/tasks/{task_id}/enqueue")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["queue"]["backend"] == "local"

    worker_result = run_queued_once(make_settings(tmp_path))

    assert worker_result["processed"] == 1
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "completed"
    assert any(artifact["path"] == "scene.xml" for artifact in task["artifacts"])


def test_local_worker_only_consumes_explicitly_enqueued_tasks(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    task_id = create_mesh_task(client, tmp_path)

    worker_result = run_queued_once(make_settings(tmp_path))

    assert worker_result == {"processed": 0, "failed": 0, "task_ids": []}
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "queued"


def test_completed_task_publishes_artifacts_to_local_object_storage(tmp_path: Path) -> None:
    client = make_client(tmp_path, {"storage_backend": "local", "storage_dir": tmp_path / "object-store"})
    task_id = create_mesh_task(client, tmp_path)

    run_response = client.post(f"/api/tasks/{task_id}/run")

    assert run_response.status_code == 200
    task = run_response.json()
    scene_xml = next(artifact for artifact in task["artifacts"] if artifact["path"] == "scene.xml")
    assert scene_xml["storage_url"] == f"/api/storage/tasks/{task_id}/scene.xml"
    storage_response = client.get(scene_xml["storage_url"])
    assert storage_response.status_code == 200
    assert "<mujoco" in storage_response.text


def test_simulation_package_verification_api_validates_export_formats_and_references(tmp_path: Path) -> None:
    client = make_client(tmp_path, {"storage_backend": "local", "storage_dir": tmp_path / "object-store"})
    task_id = create_mesh_task(client, tmp_path)
    run_response = client.post(f"/api/tasks/{task_id}/run")
    assert run_response.status_code == 200

    verify_response = client.post(f"/api/tasks/{task_id}/verify-simulation")

    assert verify_response.status_code == 200
    task = verify_response.json()
    validation = task["report"]["package_validation"]
    assert validation["valid"] is True
    assert validation["artifact_completeness"]["valid"] is True
    assert validation["manifest"]["valid"] is True
    assert validation["mjcf"]["mujoco_load_valid"] is True
    assert validation["mjcf"]["step_valid"] is True
    assert validation["urdf"]["valid"] is True
    assert validation["usd"]["valid"] is True
    assert validation["usdz"]["valid"] is True
    report_artifact = next(artifact for artifact in task["artifacts"] if artifact["path"] == "report.json")
    assert client.get(report_artifact["storage_url"]).json()["package_validation"]["valid"] is True


def test_simulation_package_verification_runs_configured_native_simulator_adapters(tmp_path: Path) -> None:
    validator_script = tmp_path / "native_validator.py"
    record_path = tmp_path / "native-validator-record.txt"
    validator_script.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "simulator, record, package_dir, mjcf_path, usd_path, usdz_path, manifest_path, zip_path = sys.argv[1:9]",
                "for value in [package_dir, mjcf_path, usd_path, usdz_path, manifest_path, zip_path]:",
                "    if not Path(value).exists():",
                "        raise SystemExit(f'missing:{value}')",
                "with Path(record).open('a', encoding='utf-8') as handle:",
                "    handle.write(f'{simulator}|{Path(package_dir).name}|{Path(mjcf_path).name}|{Path(usd_path).name}|{Path(usdz_path).name}|{Path(zip_path).name}\\n')",
            ]
        ),
        encoding="utf-8",
    )
    command_template = (
        f'"{sys.executable}" "{validator_script}" {{simulator}} "{record_path}" '
        '"{package_dir}" "{mjcf_path}" "{usd_path}" "{usdz_path}" "{manifest_path}" "{zip_path}"'
    )
    client = make_client(
        tmp_path,
        {
            "storage_backend": "local",
            "storage_dir": tmp_path / "object-store",
            "motrixsim_validate_command": command_template,
            "isaacsim_validate_command": command_template,
            "genesis_validate_command": command_template,
        },
    )
    task_id = create_mesh_task(client, tmp_path)
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    verify_response = client.post(f"/api/tasks/{task_id}/verify-simulation")

    assert verify_response.status_code == 200
    validation = verify_response.json()["report"]["package_validation"]
    native = validation["native_simulators"]
    assert native["valid"] is True
    assert native["motrixsim"]["valid"] is True
    assert native["motrixsim"]["command_configured"] is True
    assert native["isaacsim"]["valid"] is True
    assert native["genesis"]["valid"] is True
    lines = record_path.read_text(encoding="utf-8").splitlines()
    assert {line.split("|", 1)[0] for line in lines} == {"motrixsim", "isaacsim", "genesis"}
    assert all("|scene.xml|scene.usd|scene.usdz|real2sim_package.zip" in line for line in lines)


def test_native_simulator_adapter_failure_is_reported_as_failed_validation(tmp_path: Path) -> None:
    failing_script = tmp_path / "failing_validator.py"
    failing_script.write_text("raise SystemExit('native import failed')\n", encoding="utf-8")
    client = make_client(
        tmp_path,
        {
            "motrixsim_validate_command": f'"{sys.executable}" "{failing_script}"',
        },
    )
    task_id = create_mesh_task(client, tmp_path)
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    verify_response = client.post(f"/api/tasks/{task_id}/verify-simulation")

    assert verify_response.status_code == 200
    native = verify_response.json()["report"]["package_validation"]["native_simulators"]
    assert native["valid"] is False
    assert native["motrixsim"]["valid"] is False
    assert native["motrixsim"]["attempted"] is True
    assert native["motrixsim"]["exit_code"] != 0
    assert "native import failed" in native["motrixsim"]["stderr"]


def test_genesis_builtin_validator_loads_completed_package_when_genesis_is_installed(tmp_path: Path) -> None:
    pytest.importorskip("genesis")
    client = make_client(tmp_path, {"storage_backend": "local", "storage_dir": tmp_path / "object-store"})
    task_id = create_mesh_task(client, tmp_path)
    assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

    verify_response = client.post(f"/api/tasks/{task_id}/verify-simulation")

    assert verify_response.status_code == 200
    genesis = verify_response.json()["report"]["package_validation"]["native_simulators"]["genesis"]
    assert genesis["valid"] is True
    assert genesis["builtin"] is True
    assert genesis["attempted"] is True
    assert genesis["steps"] == 10


def test_enqueue_completed_task_is_rejected_instead_of_reporting_false_success(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    task_id = create_mesh_task(client, tmp_path)
    run_response = client.post(f"/api/tasks/{task_id}/run")
    assert run_response.status_code == 200

    response = client.post(f"/api/tasks/{task_id}/enqueue")

    assert response.status_code == 409
    assert response.json()["detail"] == "task_not_runnable"


def test_non_local_artifact_publish_fails_explicitly_without_configured_backend(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "scene.xml").write_text("<mujoco />", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsupported_storage_backend"):
        publish_artifacts_to_storage(
            storage_backend="unsupported",
            storage_dir=tmp_path / "object-store",
            public_base_url="http://testserver",
            task_id="task-001",
            output_dir=output_dir,
            artifacts=[{"path": "scene.xml", "url": "/api/artifacts/task-001/scene.xml"}],
        )


def test_health_reports_postgres_unavailable_without_crashing(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        {
            "database_url": "postgresql://real2sim:real2sim@127.0.0.1:1/real2sim",
            "database_connect_timeout_seconds": 1,
        },
    )

    payload = client.get("/api/health").json()

    assert payload["database"]["backend"] == "postgresql"
    assert payload["database"]["available"] is False
    assert payload["database"]["reason"]


def test_s3_storage_health_requires_real_bucket_configuration(tmp_path: Path) -> None:
    client = make_client(tmp_path, {"storage_backend": "s3"})

    payload = client.get("/api/health").json()

    assert payload["storage_backend"]["backend"] == "s3"
    assert payload["storage_backend"]["available"] is False
    assert payload["storage_backend"]["reason"] == "s3_bucket_required"


def test_redis_queue_without_server_fails_explicitly(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, {"queue_backend": "redis", "redis_url": "redis://127.0.0.1:1/0"})

    result = enqueue_task(settings, "task-001")

    assert result.ok is False
    assert result.backend == "redis"
    assert result.reason == "redis_unavailable"
