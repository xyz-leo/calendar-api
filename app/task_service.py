from datetime import date, datetime
from functools import partial

from fastapi import Depends
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.google_api_errors import execute_google_request
from app.google_oauth import get_user_credentials
from app.models import User
from app.task_schemas import Task, TaskInput

_execute = partial(execute_google_request, api_label="Google Tasks API")

# Every Google account has exactly one default task list; picking a specific list isn't
# exposed here — same "not user-configurable yet" scope note calendar_service.py's
# HOLIDAY_CALENDAR_ID already carries.
TASKLIST_ID = "@default"


class TaskService:
    def __init__(self, tasks_client):
        self.tasks_client = tasks_client

    def list_tasks(
        self, due_min: datetime | None = None, due_max: datetime | None = None
    ) -> list[Task]:
        params = {"tasklist": TASKLIST_ID}
        if due_min is not None:
            params["dueMin"] = due_min.isoformat()
        if due_max is not None:
            params["dueMax"] = due_max.isoformat()
        # showCompleted defaults to False — a completed task drops out of this list
        # immediately, matching Google's own Tasks UI (completed items move out of the
        # main list rather than staying visible crossed-out).

        tasks: list[Task] = []
        page_token = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            raw = _execute(
                self.tasks_client.tasks().list(**params), not_found_detail="Task list not found"
            )
            for item in raw.get("items", []):
                # A task can genuinely have no due date at all ("someday" tasks) —
                # those don't fit a date-based agenda, so they're skipped rather than
                # given a fabricated date. Documented limitation, see docs/architecture.md.
                if "due" not in item:
                    continue
                tasks.append(self._normalize(item))
            page_token = raw.get("nextPageToken")
            if not page_token:
                break
        return tasks

    def get_task(self, task_id: str) -> Task:
        raw = _execute(
            self.tasks_client.tasks().get(tasklist=TASKLIST_ID, task=task_id),
            not_found_detail="Task not found",
        )
        return self._normalize(raw)

    def create_task(self, task: TaskInput) -> Task:
        raw = _execute(
            self.tasks_client.tasks().insert(tasklist=TASKLIST_ID, body=task.to_google_payload())
        )
        return self._normalize(raw)

    def update_task(self, task_id: str, task: TaskInput) -> Task:
        raw = _execute(
            self.tasks_client.tasks().patch(
                tasklist=TASKLIST_ID, task=task_id, body=task.to_google_payload()
            ),
            not_found_detail="Task not found",
        )
        return self._normalize(raw)

    def delete_task(self, task_id: str) -> None:
        _execute(
            self.tasks_client.tasks().delete(tasklist=TASKLIST_ID, task=task_id),
            not_found_detail="Task not found",
        )

    def _normalize(self, raw: dict) -> Task:
        return Task(
            id=raw["id"],
            title=raw.get("title", ""),
            notes=raw.get("notes"),
            due=date.fromisoformat(raw["due"][:10]),
            status=raw.get("status", "needsAction"),
        )


def get_task_service(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TaskService:
    credentials = get_user_credentials(current_user, db)
    tasks_client = build("tasks", "v1", credentials=credentials, cache_discovery=False)
    return TaskService(tasks_client)
