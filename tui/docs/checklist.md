# Known gaps / not done yet

Deploying the TUI and the real OAuth login flow (replacing the `calctl.sh token`
stopgap) are tracked separately and aren't included here.

- **No automated tests.** Everything has been verified manually (or with throwaway
  headless scripts) against the real Docker API during development. None of that is
  a persisted test suite. The API side has one; the TUI doesn't.

- **Only shows "upcoming" events — no date-range browsing.** The event list always
  fetches with no date filter. The API already supports `from`/`to`/`range` query
  params for this; the TUI doesn't use them. No way to look at last month, jump to a
  specific date, or see anything in the past.

- **No search/filter in the list.** With more than a screenful of events, no way to
  jump to or filter for a specific one — just scrolling.

- **Recurring-event edit semantics aren't addressed.** Editing an instance of a
  recurring series just PATCHes that one instance. There's no UI acknowledgment of
  Google's "this event / this and following / all events" distinction, so it's easy
  to not realize which scope is actually being affected.

- **No loading indicator during API calls.** Probably fine since the API is local
  and fast, but worth knowing if it's ever pointed at something slower.

- **Recurring series creation has never been exercised through the actual form** —
  only via the seed script used during development.
