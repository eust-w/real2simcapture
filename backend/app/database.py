from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def database_backend(database_url: str) -> str:
    scheme = urlparse(database_url).scheme
    if scheme == "sqlite":
        return "sqlite"
    if scheme in {"postgresql", "postgres"}:
        return "postgresql"
    return scheme or "unknown"


def sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("database_url is not sqlite:///")
    return Path(database_url[len(prefix) :])


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _inflate_task(task: dict[str, Any]) -> dict[str, Any]:
    for key, fallback in [("logs", []), ("artifacts", [])]:
        value = task.get(key)
        task[key] = json.loads(value) if isinstance(value, str) and value else value or fallback
    for key in ["report", "scene"]:
        value = task.get(key)
        task[key] = json.loads(value) if isinstance(value, str) and value else value
    return task


class SQLiteDatabase:
    backend = "sqlite"

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                create table if not exists projects (
                    id text primary key,
                    name text not null,
                    description text not null default '',
                    created_at text not null
                );

                create table if not exists tasks (
                    id text primary key,
                    project_id text not null,
                    name text not null,
                    mode text not null,
                    category text not null,
                    status text not null,
                    input_path text not null,
                    original_filename text not null,
                    material_category text,
                    mass_kg real,
                    friction real,
                    failure_reason text,
                    logs text not null,
                    report text,
                    scene text,
                    artifacts text not null,
                    created_at text not null,
                    updated_at text not null,
                    foreign key(project_id) references projects(id)
                );

                create table if not exists task_queue (
                    id integer primary key autoincrement,
                    task_id text not null,
                    enqueued_at text not null,
                    foreign key(task_id) references tasks(id)
                );
                create index if not exists idx_task_queue_enqueued_at on task_queue(enqueued_at, id);
                """
            )
            self._ensure_sqlite_task_columns(connection)

    def _ensure_sqlite_task_columns(self, connection: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in connection.execute("pragma table_info(tasks)").fetchall()}
        if "material_category" not in columns:
            connection.execute("alter table tasks add column material_category text")

    def healthcheck(self) -> None:
        with self.connect() as connection:
            connection.execute("select 1").fetchone()

    def create_project(self, project: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "insert into projects (id, name, description, created_at) values (?, ?, ?, ?)",
                (project["id"], project["name"], project.get("description", ""), project["created_at"]),
            )
        return project

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("select * from projects order by created_at desc").fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("select * from projects where id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def create_task(self, task: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                insert into tasks (
                    id, project_id, name, mode, category, status, input_path, original_filename,
                    material_category, mass_kg, friction, failure_reason, logs, report, scene, artifacts, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["id"],
                    task["project_id"],
                    task["name"],
                    task["mode"],
                    task["category"],
                    task["status"],
                    task["input_path"],
                    task["original_filename"],
                    task.get("material_category"),
                    task.get("mass_kg"),
                    task.get("friction"),
                    task.get("failure_reason"),
                    _json_dumps(task.get("logs", [])),
                    _json_dumps(task.get("report")) if task.get("report") is not None else None,
                    _json_dumps(task.get("scene")) if task.get("scene") is not None else None,
                    _json_dumps(task.get("artifacts", [])),
                    task["created_at"],
                    task["updated_at"],
                ),
            )
        return task

    def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from tasks"
        params: tuple[Any, ...] = ()
        if project_id:
            query += " where project_id = ?"
            params = (project_id,)
        query += " order by created_at desc"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_inflate_task(dict(row)) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("select * from tasks where id = ?", (task_id,)).fetchone()
        return _inflate_task(dict(row)) if row else None

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        encoded = _encode_task_fields(fields)
        assignments = ", ".join(f"{key} = ?" for key in encoded)
        params = tuple(encoded.values()) + (task_id,)
        with self.connect() as connection:
            connection.execute(f"update tasks set {assignments} where id = ?", params)
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def enqueue_task(self, task_id: str) -> None:
        with self.connect() as connection:
            connection.execute("insert into task_queue (task_id, enqueued_at) values (?, ?)", (task_id, utc_now()))

    def pop_queued_task(self) -> str | None:
        with self.connect() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                """
                select task_queue.id, task_queue.task_id
                from task_queue
                join tasks on tasks.id = task_queue.task_id
                where tasks.status = 'queued'
                order by task_queue.id asc
                limit 1
                """
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    delete from task_queue
                    where task_id not in (select id from tasks where status = 'queued')
                    """
                )
                return None
            connection.execute("delete from task_queue where id = ?", (row["id"],))
            return str(row["task_id"])


class PostgresDatabase:
    backend = "postgresql"

    def __init__(self, database_url: str, connect_timeout_seconds: int = 3):
        self.database_url = database_url
        self.connect_timeout_seconds = connect_timeout_seconds

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:
            raise RuntimeError(f"postgres_dependency_missing: {exc}") from exc

        connection = psycopg.connect(
            self.database_url,
            connect_timeout=self.connect_timeout_seconds,
            row_factory=dict_row,
        )
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                create table if not exists projects (
                    id text primary key,
                    name text not null,
                    description text not null default '',
                    created_at text not null
                )
                """
            )
            connection.execute(
                """
                create table if not exists tasks (
                    id text primary key,
                    project_id text not null references projects(id),
                    name text not null,
                    mode text not null,
                    category text not null,
                    status text not null,
                    input_path text not null,
                    original_filename text not null,
                    material_category text,
                    mass_kg double precision,
                    friction double precision,
                    failure_reason text,
                    logs jsonb not null,
                    report jsonb,
                    scene jsonb,
                    artifacts jsonb not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            connection.execute("alter table tasks add column if not exists material_category text")
            connection.execute(
                """
                create table if not exists task_queue (
                    id bigserial primary key,
                    task_id text not null references tasks(id),
                    enqueued_at text not null
                )
                """
            )
            connection.execute("create index if not exists idx_task_queue_enqueued_at on task_queue(enqueued_at, id)")

    def healthcheck(self) -> None:
        self.init_schema()
        with self.connect() as connection:
            connection.execute("select 1").fetchone()

    def create_project(self, project: dict[str, Any]) -> dict[str, Any]:
        self.init_schema()
        with self.connect() as connection:
            connection.execute(
                "insert into projects (id, name, description, created_at) values (%s, %s, %s, %s)",
                (project["id"], project["name"], project.get("description", ""), project["created_at"]),
            )
        return project

    def list_projects(self) -> list[dict[str, Any]]:
        self.init_schema()
        with self.connect() as connection:
            rows = connection.execute("select * from projects order by created_at desc").fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        self.init_schema()
        with self.connect() as connection:
            row = connection.execute("select * from projects where id = %s", (project_id,)).fetchone()
        return dict(row) if row else None

    def create_task(self, task: dict[str, Any]) -> dict[str, Any]:
        self.init_schema()
        with self.connect() as connection:
            connection.execute(
                """
                insert into tasks (
                    id, project_id, name, mode, category, status, input_path, original_filename,
                    material_category, mass_kg, friction, failure_reason, logs, report, scene, artifacts, created_at, updated_at
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task["id"],
                    task["project_id"],
                    task["name"],
                    task["mode"],
                    task["category"],
                    task["status"],
                    task["input_path"],
                    task["original_filename"],
                    task.get("material_category"),
                    task.get("mass_kg"),
                    task.get("friction"),
                    task.get("failure_reason"),
                    _jsonb(task.get("logs", [])),
                    _jsonb(task.get("report")) if task.get("report") is not None else None,
                    _jsonb(task.get("scene")) if task.get("scene") is not None else None,
                    _jsonb(task.get("artifacts", [])),
                    task["created_at"],
                    task["updated_at"],
                ),
            )
        return task

    def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        self.init_schema()
        query = "select * from tasks"
        params: tuple[Any, ...] = ()
        if project_id:
            query += " where project_id = %s"
            params = (project_id,)
        query += " order by created_at desc"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_inflate_task(dict(row)) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        self.init_schema()
        with self.connect() as connection:
            row = connection.execute("select * from tasks where id = %s", (task_id,)).fetchone()
        return _inflate_task(dict(row)) if row else None

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        self.init_schema()
        encoded = _encode_task_fields(fields, postgres=True)
        assignments = ", ".join(f"{key} = %s" for key in encoded)
        params = tuple(encoded.values()) + (task_id,)
        with self.connect() as connection:
            connection.execute(f"update tasks set {assignments} where id = %s", params)
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def enqueue_task(self, task_id: str) -> None:
        self.init_schema()
        with self.connect() as connection:
            connection.execute("insert into task_queue (task_id, enqueued_at) values (%s, %s)", (task_id, utc_now()))

    def pop_queued_task(self) -> str | None:
        self.init_schema()
        with self.connect() as connection:
            row = connection.execute(
                """
                select task_queue.id, task_queue.task_id
                from task_queue
                join tasks on tasks.id = task_queue.task_id
                where tasks.status = 'queued'
                order by task_queue.id asc
                limit 1
                for update skip locked
                """
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    delete from task_queue
                    where task_id not in (select id from tasks where status = 'queued')
                    """
                )
                return None
            connection.execute("delete from task_queue where id = %s", (row["id"],))
            return str(row["task_id"])


class Database:
    def __init__(self, location: Path | str, connect_timeout_seconds: int = 3):
        if isinstance(location, Path):
            self._backend = SQLiteDatabase(location)
        else:
            backend = database_backend(location)
            if backend == "sqlite":
                self._backend = SQLiteDatabase(sqlite_path_from_url(location))
            elif backend == "postgresql":
                self._backend = PostgresDatabase(location, connect_timeout_seconds)
            else:
                raise ValueError(f"unsupported_database_backend:{backend}")

    @property
    def backend(self) -> str:
        return self._backend.backend

    def healthcheck(self) -> None:
        self._backend.healthcheck()

    def create_project(self, project: dict[str, Any]) -> dict[str, Any]:
        return self._backend.create_project(project)

    def list_projects(self) -> list[dict[str, Any]]:
        return self._backend.list_projects()

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._backend.get_project(project_id)

    def create_task(self, task: dict[str, Any]) -> dict[str, Any]:
        return self._backend.create_task(task)

    def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._backend.list_tasks(project_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._backend.get_task(task_id)

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        return self._backend.update_task(task_id, **fields)

    def enqueue_task(self, task_id: str) -> None:
        self._backend.enqueue_task(task_id)

    def pop_queued_task(self) -> str | None:
        return self._backend.pop_queued_task()


def database_health(database_url: str, connect_timeout_seconds: int = 3) -> dict[str, str | bool | None]:
    backend = database_backend(database_url)
    try:
        database = Database(database_url, connect_timeout_seconds)
        database.healthcheck()
        return {"backend": database.backend, "available": True, "reason": None}
    except Exception as exc:
        return {"backend": backend, "available": False, "reason": str(exc)}


def _encode_task_fields(fields: dict[str, Any], postgres: bool = False) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in fields.items():
        if key in {"logs", "report", "scene", "artifacts"} and value is not None:
            encoded[key] = _jsonb(value) if postgres else _json_dumps(value)
        else:
            encoded[key] = value
    return encoded


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except Exception as exc:
        raise RuntimeError(f"postgres_dependency_missing: {exc}") from exc
    return Jsonb(value)
