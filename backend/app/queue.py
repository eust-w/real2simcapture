from __future__ import annotations

from dataclasses import dataclass

from .database import Database
from .pipeline import run_task
from .settings import AppSettings


@dataclass(frozen=True)
class QueueResult:
    ok: bool
    backend: str
    task_id: str
    reason: str | None = None


def enqueue_task(settings: AppSettings, task_id: str) -> QueueResult:
    if settings.queue_backend == "local":
        try:
            Database(settings.database_url, settings.database_connect_timeout_seconds).enqueue_task(task_id)
            return QueueResult(ok=True, backend="local", task_id=task_id)
        except Exception as exc:
            return QueueResult(ok=False, backend="local", task_id=task_id, reason=f"local_queue_unavailable:{exc}")
    if settings.queue_backend == "redis":
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            client.rpush(settings.redis_queue_name, task_id)
            return QueueResult(ok=True, backend="redis", task_id=task_id)
        except Exception:
            return QueueResult(ok=False, backend="redis", task_id=task_id, reason="redis_unavailable")
    return QueueResult(ok=False, backend=settings.queue_backend, task_id=task_id, reason="unsupported_queue_backend")


def queue_health(settings: AppSettings) -> dict[str, str | bool | None]:
    if settings.queue_backend == "local":
        try:
            Database(settings.database_url, settings.database_connect_timeout_seconds).healthcheck()
            return {"backend": "local", "available": True, "reason": None}
        except Exception as exc:
            return {"backend": "local", "available": False, "reason": f"local_queue_unavailable:{exc}"}
    if settings.queue_backend == "redis":
        result = enqueue_task(settings, "__healthcheck__")
        if result.ok:
            try:
                import redis

                redis.Redis.from_url(settings.redis_url, decode_responses=True).lrem(settings.redis_queue_name, 1, "__healthcheck__")
            except Exception:
                pass
            return {"backend": "redis", "available": True, "reason": None}
        return {"backend": "redis", "available": False, "reason": result.reason}
    return {"backend": settings.queue_backend, "available": False, "reason": "unsupported_queue_backend"}


def pop_queued_task(settings: AppSettings, db: Database) -> str | None:
    if settings.queue_backend == "redis":
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
            value = client.lpop(settings.redis_queue_name)
            return value if isinstance(value, str) else None
        except Exception:
            return None
    return db.pop_queued_task()


def run_queued_once(settings: AppSettings) -> dict[str, int | list[str]]:
    db = Database(settings.database_url, settings.database_connect_timeout_seconds)
    task_id = pop_queued_task(settings, db)
    if task_id is None:
        return {"processed": 0, "failed": 0, "task_ids": []}
    _task, status_code = run_task(db, settings, task_id)
    return {"processed": 1, "failed": 1 if status_code >= 400 else 0, "task_ids": [task_id]}
