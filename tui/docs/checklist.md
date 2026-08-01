# Known gaps / not done yet

Deploying the TUI and the real OAuth login flow (replacing the `calctl.sh token`
stopgap) are tracked separately and aren't included here.

- **No automated tests.** Everything has been verified manually (or with throwaway
  headless scripts) against the real Docker API during development. None of that is
  a persisted test suite. The API side has one; the TUI doesn't.

- **No text search in the list.** With more than a screenful of events, no way to
  jump to or filter for a specific one by name — just scrolling (date-range
  filtering via `f` — today/week/month/a specific month/a specific date — is
  already covered, see README). The API doesn't expose search either:
  `calendar_service.list_events` only forwards `timeMin`/`timeMax` to Google, never
  Google's own `q` (free-text) param, and the `/events` route doesn't accept one.
  This should be added server-side first (`q` through `calendar_service.list_events`
  → the `/events` route → the TUI, the same pattern already used for
  `from`/`to`/`range`) rather than done as a client-side substring filter over
  whatever's already fetched — the API is what should own query semantics, so any
  other client hitting it gets the same search behavior for free instead of every
  client reimplementing its own weaker approximation.

- **Recurring-event edit semantics aren't addressed.** Editing an instance of a
  recurring series just PATCHes that one instance. There's no UI acknowledgment of
  Google's "this event / this and following / all events" distinction, so it's easy
  to not realize which scope is actually being affected.

- **No loading indicator during API calls.** Probably fine since the API is local
  and fast, but worth knowing if it's ever pointed at something slower.

- **Recurring series creation has never been exercised through the actual form** —
  only via the seed script used during development.
