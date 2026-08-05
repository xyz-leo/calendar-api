from fastapi.testclient import TestClient

from app.main import app
from app.task_service import TaskService, get_task_service
from tests.conftest import FakeTasksClient, make_http_error, raw_task


def _client_with_fake_tasks(fake_tasks_client: FakeTasksClient) -> TestClient:
    app.dependency_overrides[get_task_service] = lambda: TaskService(fake_tasks_client)
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_list_tasks_route_returns_normalized_tasks():
    fake = FakeTasksClient()
    fake.queue("list", result={"items": [raw_task(title="Routed")]})
    client = _client_with_fake_tasks(fake)

    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Routed"


def test_get_task_route_404_on_missing_task():
    fake = FakeTasksClient()
    fake.queue("get", error=make_http_error(404))
    client = _client_with_fake_tasks(fake)

    response = client.get("/tasks/does-not-exist")

    assert response.status_code == 404
    assert "task not found" in response.json()["detail"].lower()


def test_create_task_route():
    fake = FakeTasksClient()
    fake.queue("insert", result=raw_task(title="Created"))
    client = _client_with_fake_tasks(fake)

    response = client.post("/tasks", json={"title": "Created", "due": "2026-08-15"})

    assert response.status_code == 201
    assert response.json()["title"] == "Created"


def test_update_task_route():
    fake = FakeTasksClient()
    fake.queue("patch", result=raw_task(status="completed"))
    client = _client_with_fake_tasks(fake)

    response = client.patch(
        "/tasks/task1", json={"title": "x", "due": "2026-08-15", "completed": True}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_delete_task_route():
    fake = FakeTasksClient()
    fake.queue("delete", result=None)
    client = _client_with_fake_tasks(fake)

    response = client.delete("/tasks/task1")

    assert response.status_code == 204


def test_create_task_route_rejects_missing_due_date():
    fake = FakeTasksClient()
    client = _client_with_fake_tasks(fake)

    response = client.post("/tasks", json={"title": "No due date"})

    assert response.status_code == 422
