# Known gaps / not done yet

- **Login token delivery only works for the TUI.** `/auth/callback`'s two response
  modes — plain JSON, or the `127.0.0.1:<port>` loopback redirect — only serve a
  browser being copy-pasted from and a local CLI/TUI respectively. A real website
  or mobile client would each need their own delivery mechanism, neither of which
  exists yet:
  - **Website** — `/auth/callback` would need to set the JWT via `Set-Cookie`
    (`HttpOnly`, `Secure`, `SameSite`) instead of returning it as JSON, so
    JavaScript never touches the token directly (keeps it safe from XSS). This
    also means adding CSRF protection, since a cookie gets attached to requests
    automatically instead of being explicitly set in an `Authorization` header
    the way the TUI does it now.
  - **Mobile** — needs a redirect the OS itself can route to the installed app:
    either a custom URL scheme (`calendarapp://callback`) or, better, a
    Universal Link/App Link (verified ownership of a real `https://` URL, so a
    different app can't register the same scheme and steal the redirect). Modern
    practice also runs the actual login page through an OS-owned session
    (`ASWebAuthenticationSession`/Chrome Custom Tabs) rather than an embedded
    webview the app fully controls, so the app itself never has a chance to see
    or phish the Google password field.

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
