import http.server
import queue
import threading
from urllib.parse import parse_qs, urlparse

_SUCCESS_BODY = b"""\
<!doctype html>
<html><body style="font: 16px sans-serif; padding: 3em; text-align: center;">
<p>Login successful. You can close this tab and return to the terminal.</p>
</body></html>
"""


def _make_handler(result: "queue.Queue[str | None]") -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            token = parse_qs(urlparse(self.path).query).get("token", [None])[0]
            result.put(token)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_SUCCESS_BODY)

        def log_message(self, *args: object) -> None:
            # Default BaseHTTPRequestHandler logging writes to stderr, over the TUI's
            # alternate screen buffer — and would print the token-bearing request line.
            pass

    return _Handler


class LoopbackServer:
    """A one-shot local HTTP server that captures a single ?token=... callback.

    Binding to 127.0.0.1 (never 0.0.0.0) is what makes it safe to leave listening
    for the caller's whole timeout window — nothing off-machine can ever reach it.
    Port 0 means the OS picks a free ephemeral port, so there's no bind-conflict
    handling to write.
    """

    def __init__(self) -> None:
        self._result: "queue.Queue[str | None]" = queue.Queue(maxsize=1)
        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), _make_handler(self._result))
        self.port = self._httpd.server_address[1]

    def serve_one(self, timeout: float, cancel_event: threading.Event) -> str | None:
        """Blocks the calling thread until one request arrives, `cancel_event` is
        set, or `timeout` seconds elapse. Returns the captured token, or None."""
        # handle_request() has no timeout of its own — polling it with a short
        # per-iteration server timeout is what lets a cancel (or the overall
        # deadline) unblock this loop without needing to interrupt a blocking call.
        self._httpd.timeout = 0.5
        remaining = timeout
        while remaining > 0 and not cancel_event.is_set():
            self._httpd.handle_request()
            if not self._result.empty():
                break
            remaining -= self._httpd.timeout
        self._httpd.server_close()
        return self._result.get_nowait() if not self._result.empty() else None
