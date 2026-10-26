from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_optional_infrastructure_ports_bind_only_to_loopback():
    services = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())["services"]
    ports = [port for service in services.values() for port in service.get("ports", [])]
    assert ports
    assert all(port.startswith("127.0.0.1:") for port in ports)


def test_optional_infrastructure_requires_user_supplied_passwords():
    services = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())["services"]
    credentials = [
        services["postgres"]["environment"]["POSTGRES_PASSWORD"],
        services["minio"]["environment"]["MINIO_ROOT_PASSWORD"],
        services["minio-create-bucket"]["environment"]["MINIO_ROOT_PASSWORD"],
    ]
    assert all(":?" in value and ":-" not in value for value in credentials)


def test_capture_storage_is_not_anonymous_by_default():
    services = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())["services"]
    command = services["minio-create-bucket"]["entrypoint"][-1]
    assert 'mc anonymous set private "local/$${REAL2SIM_S3_BUCKET}"' in command
    assert "mc anonymous set download" not in command
