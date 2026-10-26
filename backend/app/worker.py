from __future__ import annotations

import argparse
import sys

from .database import Database
from .pipeline import run_task
from .queue import run_queued_once
from .settings import AppSettings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run queued iPhone Real2Sim reconstruction jobs.")
    parser.add_argument("--once", action="store_true", help="Run currently queued jobs and exit.")
    parser.add_argument("--task-id", help="Run one task id.")
    args = parser.parse_args()

    settings = AppSettings()
    if not args.task_id:
        result = run_queued_once(settings)
        if result["processed"] == 0:
            print("No queued jobs.")
            return 0
        print(f"processed={result['processed']} failed={result['failed']} task_ids={','.join(result['task_ids'])}")
        return 1 if result["failed"] else 0

    db = Database(settings.database_url, settings.database_connect_timeout_seconds)
    tasks = [db.get_task(args.task_id)] if args.task_id else db.list_tasks()
    runnable = [task for task in tasks if task and task["status"] in {"queued", "failed"}]
    if not runnable:
        print("No queued jobs.")
        return 0
    exit_code = 0
    for task in runnable:
        updated, status_code = run_task(db, settings, task["id"])
        print(f"{updated['id']} {updated['status']} {updated.get('failure_reason') or ''}".strip())
        if status_code >= 400:
            exit_code = 1
        if args.once:
            break
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
