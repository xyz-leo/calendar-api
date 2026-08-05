import pytest
from fastapi import HTTPException

from app.task_service import TaskService
from tests.conftest import FakeTasksClient, make_http_error, raw_task


def test_list_tasks_normalizes():
    client = FakeTasksClient()
    client.queue("list", result={"items": [raw_task()]})
    service = TaskService(client)

    tasks = service.list_tasks()

    assert len(tasks) == 1
    assert tasks[0].id == "task1"
    assert tasks[0].title == "Test task"
    assert tasks[0].status == "needsAction"
    assert str(tasks[0].due) == "2026-08-15"


def test_list_tasks_skips_items_with_no_due_date():
    client = FakeTasksClient()
    client.queue(
        "list",
        result={"items": [raw_task("dated"), {"id": "someday", "title": "No due date", "status": "needsAction"}]},
    )
    service = TaskService(client)

    tasks = service.list_tasks()

    assert [t.id for t in tasks] == ["dated"]


def test_list_tasks_follows_pagination():
    client = FakeTasksClient()
    client.queue("list", result={"items": [raw_task("a")], "nextPageToken": "page2"})
    client.queue("list", result={"items": [raw_task("b")]})
    service = TaskService(client)

    tasks = service.list_tasks()

    assert [t.id for t in tasks] == ["a", "b"]
    assert client.calls[1][1]["pageToken"] == "page2"


def test_list_tasks_passes_due_bounds_to_google():
    import datetime

    client = FakeTasksClient()
    client.queue("list", result={"items": []})
    service = TaskService(client)
    due_min = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
    due_max = datetime.datetime(2026, 8, 31, tzinfo=datetime.timezone.utc)

    service.list_tasks(due_min=due_min, due_max=due_max)

    _, kwargs = client.calls[0]
    assert kwargs["dueMin"] == due_min.isoformat()
    assert kwargs["dueMax"] == due_max.isoformat()
    assert kwargs["tasklist"] == "@default"


def test_get_task_normalizes():
    client = FakeTasksClient()
    client.queue("get", result=raw_task(title="Fetched"))
    service = TaskService(client)

    task = service.get_task("task1")

    assert task.title == "Fetched"


def test_create_task_sends_payload_and_normalizes_response():
    from app.task_schemas import TaskInput

    client = FakeTasksClient()
    client.queue("insert", result=raw_task(title="Created"))
    service = TaskService(client)
    task_in = TaskInput(title="Created", due="2026-08-15")

    result = service.create_task(task_in)

    assert result.title == "Created"
    _, kwargs = client.calls[0]
    assert kwargs["body"]["title"] == "Created"
    assert kwargs["body"]["status"] == "needsAction"


def test_create_task_completed_maps_to_completed_status():
    from app.task_schemas import TaskInput

    client = FakeTasksClient()
    client.queue("insert", result=raw_task(status="completed"))
    service = TaskService(client)
    task_in = TaskInput(title="Done already", due="2026-08-15", completed=True)

    service.create_task(task_in)

    _, kwargs = client.calls[0]
    assert kwargs["body"]["status"] == "completed"


def test_delete_task_calls_google_with_right_id():
    client = FakeTasksClient()
    client.queue("delete", result=None)
    service = TaskService(client)

    service.delete_task("task1")

    method, kwargs = client.calls[0]
    assert method == "delete"
    assert kwargs["task"] == "task1"
    assert kwargs["tasklist"] == "@default"


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_detail_snippet"),
    [
        (404, 404, "task not found"),
        (403, 403, "denied"),
        (401, 401, "expired or was revoked"),
        (500, 502, "Google Tasks API error"),
    ],
)
def test_google_errors_translate_to_clean_http_exceptions(
    status, expected_status, expected_detail_snippet
):
    client = FakeTasksClient()
    client.queue("get", error=make_http_error(status))
    service = TaskService(client)

    with pytest.raises(HTTPException) as exc_info:
        service.get_task("missing")

    assert exc_info.value.status_code == expected_status
    assert expected_detail_snippet.lower() in exc_info.value.detail.lower()
