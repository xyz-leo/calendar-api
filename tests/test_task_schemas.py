from app.task_schemas import TaskInput


def test_payload_omits_notes_when_not_given():
    t = TaskInput(title="x", due="2026-08-15")
    payload = t.to_google_payload()
    assert "notes" not in payload


def test_payload_includes_notes_when_given():
    t = TaskInput(title="x", due="2026-08-15", notes="details")
    payload = t.to_google_payload()
    assert payload["notes"] == "details"


def test_payload_due_is_midnight_utc():
    t = TaskInput(title="x", due="2026-08-15")
    assert t.to_google_payload()["due"] == "2026-08-15T00:00:00.000Z"


def test_payload_status_defaults_to_needs_action():
    t = TaskInput(title="x", due="2026-08-15")
    assert t.to_google_payload()["status"] == "needsAction"


def test_payload_status_is_completed_when_marked_done():
    t = TaskInput(title="x", due="2026-08-15", completed=True)
    assert t.to_google_payload()["status"] == "completed"
