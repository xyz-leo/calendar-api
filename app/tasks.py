from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response

from app.task_schemas import Task, TaskInput
from app.task_service import TaskService, get_task_service
from app.time_range import resolve_time_range

router = APIRouter()


@router.get("/tasks")
def list_tasks(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    service: TaskService = Depends(get_task_service),
) -> list[Task]:
    time_min, time_max = resolve_time_range(from_, to, None)
    return service.list_tasks(due_min=time_min, due_max=time_max)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, service: TaskService = Depends(get_task_service)) -> Task:
    return service.get_task(task_id)


@router.post("/tasks", status_code=201)
def create_task(task: TaskInput, service: TaskService = Depends(get_task_service)) -> Task:
    return service.create_task(task)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str, task: TaskInput, service: TaskService = Depends(get_task_service)
) -> Task:
    return service.update_task(task_id, task)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, service: TaskService = Depends(get_task_service)) -> Response:
    service.delete_task(task_id)
    return Response(status_code=204)
