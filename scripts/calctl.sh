#!/bin/sh
# calctl — a tiny CLI for manually exercising the running calendar-api.
#
# This is a development/testing convenience, not a real client: the `token`
# command mints a JWT directly from the database for whichever user already
# exists, bypassing the real Google login flow entirely (that flow needs a
# real browser and has already been proven to work — this tool is for
# exercising /events quickly and repeatedly, not for re-testing login).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TOKEN_FILE="$REPO_ROOT/tmp/cli_token"
BASE_URL="${CALCTL_BASE_URL:-http://localhost:8000}"

usage() {
    name="$(basename "$0")"
    cat <<EOF
Usage: $name <command> [args]

Commands:
  token                                     mint and cache a fresh JWT for the logged-in user
  list                                      list events            (GET  /events)
  get    <event_id>                         fetch one event        (GET  /events/{id})
  create <summary> <start> <end> [tz] [rrule]       create an event        (POST /events)
  update <event_id> <summary> <start> <end> [tz] [rrule]   update an event (PATCH /events/{id})
  delete <event_id>                         delete an event        (DELETE /events/{id})

<start>/<end> are ISO datetimes without offset, e.g. 2026-08-15T14:00:00
[tz] is an IANA timezone name (e.g. America/Sao_Paulo, Europe/Lisbon, UTC).
      Defaults to UTC if omitted.
[rrule] is a single RFC 5545 recurrence rule, e.g. "RRULE:FREQ=WEEKLY;COUNT=5".
      See docs/rfc5545.md for how to write these. Omit for a one-off event.
      To set [rrule] you must also pass [tz] (use UTC as a placeholder if needed).

Full worked examples (run them in this order to see the whole lifecycle):

  # 1. Get a token first — every other command needs one cached.
  $name token

  # 2. List whatever's currently on the calendar (starts empty).
  $name list

  # 3. Create an event. summary is one argument, so quote it if it has spaces.
  $name create "Dentist appointment" "2026-09-01T14:00:00" "2026-09-01T15:00:00" "America/Sao_Paulo"
  #   -> prints the created event's JSON, including its "id" — copy that id
  #      for the next steps. Example id used below: abc123

  # 4. Fetch that one event by the id you got back from create.
  $name get abc123

  # 5. Update it — same argument shape as create, plus the event id first.
  $name update abc123 "Dentist appointment (rescheduled)" "2026-09-01T16:00:00" "2026-09-01T17:00:00" "America/Sao_Paulo"

  # 6. Delete it. Prints "HTTP 204" on success.
  $name delete abc123

  # 7. Confirm it's gone from the listing (a direct 'get' on it would still
  #    work and show "status": "cancelled" — Google keeps a tombstone record,
  #    it does not vanish from the API immediately).
  $name list

Recurring events (RFC 5545 rule as the last argument):

  # Create a weekly standup, every Monday, 10 occurrences total.
  $name create "Team standup" "2026-08-03T09:00:00" "2026-08-03T09:15:00" \\
      "America/Sao_Paulo" "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10"

  # 'list' expands the series into individual occurrences, each with its own
  # id and a "recurring_event_id" pointing back to the series.
  $name list

  # Editing one occurrence's id only changes that single instance.
  # Editing the series' own id (the first occurrence's recurring_event_id,
  # or the id returned by 'create') changes the whole series going forward.
  $name update <occurrence_id> "Team standup (moved)" "2026-08-04T09:00:00" "2026-08-04T09:15:00"

See docs/rfc5545.md for the full RRULE syntax reference.

If a request comes back 401, the cached token likely expired — run '$name token' again.
EOF
    exit 1
}

mint_token() {
    docker compose exec -T api sh -c '
        set -a
        . /app/data/.secrets.env
        set +a
        uv run python -c "
from app.database import SessionLocal
from app.models import User
from app.security import create_access_token
db = SessionLocal()
user = db.query(User).first()
if user is None:
    raise SystemExit(\"No user found — log in through /auth/login in a browser first.\")
print(create_access_token(user.id))
"
    ' | tail -1 | tr -d '\r'
}

cmd_token() {
    mkdir -p "$(dirname "$TOKEN_FILE")"
    token="$(mint_token)"
    echo "$token" > "$TOKEN_FILE"
    echo "Token cached at $TOKEN_FILE"
}

get_token() {
    if [ ! -f "$TOKEN_FILE" ]; then
        cmd_token >&2
    fi
    cat "$TOKEN_FILE"
}

pretty() {
    if command -v python3 >/dev/null 2>&1; then
        python3 -m json.tool
    else
        cat
    fi
}

build_json() {
    # build_json <summary> <start> <end> <timezone> [rrule]
    python3 -c '
import json, sys
summary, start, end, tz = sys.argv[1:5]
payload = {"summary": summary, "start": start, "end": end, "timezone": tz}
if len(sys.argv) > 5 and sys.argv[5]:
    payload["recurrence"] = [sys.argv[5]]
print(json.dumps(payload))
' "$1" "$2" "$3" "$4" "${5:-}"
}

[ $# -ge 1 ] || usage
command="$1"
shift

case "$command" in
    token)
        cmd_token
        ;;
    list)
        curl -s -H "Authorization: Bearer $(get_token)" "$BASE_URL/events" | pretty
        ;;
    get)
        [ $# -eq 1 ] || usage
        curl -s -H "Authorization: Bearer $(get_token)" "$BASE_URL/events/$1" | pretty
        ;;
    create)
        [ $# -ge 3 ] || usage
        summary="$1"; start="$2"; end="$3"; tz="${4:-UTC}"; rrule="${5:-}"
        curl -s -X POST "$BASE_URL/events" \
            -H "Authorization: Bearer $(get_token)" \
            -H "Content-Type: application/json" \
            -d "$(build_json "$summary" "$start" "$end" "$tz" "$rrule")" | pretty
        ;;
    update)
        [ $# -ge 4 ] || usage
        event_id="$1"; summary="$2"; start="$3"; end="$4"; tz="${5:-UTC}"; rrule="${6:-}"
        curl -s -X PATCH "$BASE_URL/events/$event_id" \
            -H "Authorization: Bearer $(get_token)" \
            -H "Content-Type: application/json" \
            -d "$(build_json "$summary" "$start" "$end" "$tz" "$rrule")" | pretty
        ;;
    delete)
        [ $# -eq 1 ] || usage
        code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
            -H "Authorization: Bearer $(get_token)" "$BASE_URL/events/$1")
        echo "HTTP $code"
        ;;
    *)
        usage
        ;;
esac
