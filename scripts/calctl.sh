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
  token                       mint and cache a fresh JWT
  logout                      end session server-side (kills all tokens + Google access)
  list                        list events
  get    <event_id>           fetch one event
  create [flags]              create an event
  update <event_id> [flags]   update an event
  delete <event_id>           delete an event

Flags (create/update, any order):
  --summary <text>        required
  --start <date|datetime> required
  --end <date|datetime>   required for timed events; optional for all-day (defaults
                           to start+1 day — Google's all-day "end" is exclusive)
  --description <text>
  --location <text>
  --timezone <tz>         default UTC, e.g. America/Sao_Paulo (ignored for all-day)
  --rrule <rule>          RFC 5545 rule, see docs/rfc5545.md

Bare date ("2026-08-15") = all-day event. Full timestamp ("2026-08-15T14:00:00") = timed.

Examples:

  $name token
  $name list

  # All-day, one day (end auto-computed)
  $name create --summary "Team offsite" --start 2026-09-01 --description "Planning day"

  # Timed event
  $name create --summary "Dentist" --start 2026-09-01T14:00:00 --end 2026-09-01T15:00:00 \\
      --timezone America/Sao_Paulo

  # Recurring, weekly for 10 weeks
  $name create --summary "Standup" --start 2026-08-03T09:00:00 --end 2026-08-03T09:15:00 \\
      --timezone America/Sao_Paulo --rrule "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10"

  $name get <event_id>
  $name update <event_id> --summary "Renamed" --start 2026-09-01
  $name delete <event_id>
  $name logout

Notes:
  - Editing a recurring occurrence's own id changes just that instance; editing the
    series id (the "recurring_event_id" on any occurrence) changes the whole series.
  - Multi-day all-day events: pass --end explicitly (end is exclusive, so a 3-day
    span starting D is --end D+3).
  - Switching an event between all-day and timed via 'update' fails on Google's side
    (400 "Invalid start time") — delete and recreate instead.
  - 401? Run '$name token' again.
EOF
    exit 1
}

mint_token() {
    # Which user gets a token: if exactly one row exists (true for a normal single-
    # developer setup), that one — no guessing needed. If more than one exists, this
    # refuses to pick arbitrarily; set CALCTL_USER_EMAIL to say which one you mean.
    docker compose exec -T -e CALCTL_USER_EMAIL="${CALCTL_USER_EMAIL:-}" api sh -c '
        set -a
        . /app/data/.secrets.env
        set +a
        uv run python -c "
import os
from app.database import SessionLocal
from app.models import User
from app.security import create_access_token

db = SessionLocal()
email = os.environ.get(\"CALCTL_USER_EMAIL\")
if email:
    user = db.query(User).filter_by(email=email).first()
    if user is None:
        raise SystemExit(f\"No user with email {email!r} found.\")
else:
    users = db.query(User).all()
    if not users:
        raise SystemExit(\"No user found — log in through /auth/login in a browser first.\")
    if len(users) > 1:
        known = \", \".join(u.email for u in users)
        raise SystemExit(
            f\"Multiple users found ({known}) — set CALCTL_USER_EMAIL to pick one.\"
        )
    user = users[0]

print(create_access_token(user.id, user.session_version))
"
    '
}

cmd_token() {
    mkdir -p "$(dirname "$TOKEN_FILE")"
    # Capturing via "$(...)" (not piping mint_token's output onward) is what makes
    # its real exit code visible here — a pipe would only ever report the exit
    # code of the LAST command in it (tail/tr), silently hiding a failure upstream.
    output="$(mint_token)" || exit 1
    token="$(echo "$output" | tail -1 | tr -d '\r')"
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

# Parses --summary/--start/--end/--description/--location/--timezone/--rrule out
# of "$@" into plain shell variables of the same name. Named flags instead of
# positional arguments mean order never matters and nothing needs an empty ""
# placeholder just to reach a later argument.
parse_event_flags() {
    summary=""
    start=""
    end=""
    description=""
    location=""
    timezone="UTC"
    rrule=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --summary)     summary="$2"; shift 2 ;;
            --start)       start="$2"; shift 2 ;;
            --end)         end="$2"; shift 2 ;;
            --description) description="$2"; shift 2 ;;
            --location)    location="$2"; shift 2 ;;
            --timezone)    timezone="$2"; shift 2 ;;
            --rrule)       rrule="$2"; shift 2 ;;
            *) echo "Unknown flag: $1" >&2; usage ;;
        esac
    done
    [ -n "$summary" ] || { echo "--summary is required" >&2; usage; }
    [ -n "$start" ] || { echo "--start is required" >&2; usage; }
}

build_json() {
    # Reads the shell variables set by parse_event_flags — not passed as args,
    # since there are now seven of them and passing that many positionally
    # would just reintroduce the ordering problem this rewrite is fixing.
    python3 -c '
import json, sys
summary, start, end, description, location, tz, rrule = sys.argv[1:8]
payload = {"summary": summary, "start": start, "timezone": tz}
if end:
    payload["end"] = end
if description:
    payload["description"] = description
if location:
    payload["location"] = location
if rrule:
    payload["recurrence"] = [rrule]
print(json.dumps(payload))
' "$summary" "$start" "$end" "$description" "$location" "$timezone" "$rrule"
}

[ $# -ge 1 ] || usage
command="$1"
shift

case "$command" in
    token)
        cmd_token
        ;;
    logout)
        curl -s -X POST "$BASE_URL/auth/logout" -H "Authorization: Bearer $(get_token)" | pretty
        rm -f "$TOKEN_FILE"
        echo "Cached token removed at $TOKEN_FILE"
        ;;
    list)
        curl -s -H "Authorization: Bearer $(get_token)" "$BASE_URL/events" | pretty
        ;;
    get)
        [ $# -eq 1 ] || usage
        curl -s -H "Authorization: Bearer $(get_token)" "$BASE_URL/events/$1" | pretty
        ;;
    create)
        parse_event_flags "$@"
        curl -s -X POST "$BASE_URL/events" \
            -H "Authorization: Bearer $(get_token)" \
            -H "Content-Type: application/json" \
            -d "$(build_json)" | pretty
        ;;
    update)
        [ $# -ge 1 ] || usage
        event_id="$1"; shift
        parse_event_flags "$@"
        curl -s -X PATCH "$BASE_URL/events/$event_id" \
            -H "Authorization: Bearer $(get_token)" \
            -H "Content-Type: application/json" \
            -d "$(build_json)" | pretty
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
