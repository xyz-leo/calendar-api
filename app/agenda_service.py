from datetime import datetime

from fastapi import Depends, HTTPException

from app.calendar_service import CalendarService, event_sort_key, get_calendar_service
from app.schemas import Event
from app.task_schemas import Task
from app.task_service import TaskService, get_task_service


def _task_as_event(task: Task) -> Event:
    # The one adapter in this whole feature: folds a Task into the Event shape so the
    # merged agenda can render one list without branching on which Google API an item
    # came from (the same role is_holiday already plays). GET /tasks itself returns
    # real, unreshaped Task objects — this projection only exists for the merge below.
    start = datetime.combine(task.due, datetime.min.time())
    return Event(
        id=task.id,
        summary=task.title,
        description=task.notes,
        location=None,
        start=start,
        # A task is an instant (a due date), not a [start, end) range like the Calendar
        # all-day convention — there's nothing to make exclusive, so end == start.
        end=start,
        timezone="UTC",
        status=task.status,
        recurrence=None,
        recurring_event_id=None,
        all_day=True,
        is_holiday=False,
        is_task=True,
    )


class AgendaService:
    """Composes CalendarService + TaskService into the one merged, sorted list the
    agenda/calendar views render. This is the only module that knows both services
    exist — neither CalendarService nor TaskService imports the other."""

    def __init__(self, calendar_service: CalendarService, task_service: TaskService):
        self.calendar_service = calendar_service
        self.task_service = task_service

    def list_agenda(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        *,
        only_holidays: bool = False,
        only_tasks: bool = False,
    ) -> list[Event]:
        if only_holidays and only_tasks:
            raise HTTPException(
                status_code=400, detail="Cannot combine 'only_holidays' with 'only_tasks'"
            )
        if only_tasks:
            # Mirrors only_holidays' own "this is literally the only thing being asked
            # for" rule (see CalendarService.list_events) — a Tasks fetch failure here
            # surfaces as an error instead of a misleading empty list, unlike the
            # swallowed failure below when tasks are just one part of a bigger merge.
            tasks = self.task_service.list_tasks(due_min=time_min, due_max=time_max)
            events = [_task_as_event(t) for t in tasks]
            events.sort(key=event_sort_key)
            return events

        events = self.calendar_service.list_events(
            time_min=time_min, time_max=time_max, only_holidays=only_holidays
        )
        if not only_holidays:
            try:
                tasks = self.task_service.list_tasks(due_min=time_min, due_max=time_max)
                events.extend(_task_as_event(t) for t in tasks)
            except HTTPException:
                # Same swallow-a-hiccup precedent CalendarService's own holiday merge
                # already uses: a Tasks API hiccup (or a session that hasn't re-logged
                # in since the tasks scope was added) shouldn't take down the agenda.
                pass
        events.sort(key=event_sort_key)
        return events


def get_agenda_service(
    calendar_service: CalendarService = Depends(get_calendar_service),
    task_service: TaskService = Depends(get_task_service),
) -> AgendaService:
    return AgendaService(calendar_service, task_service)
