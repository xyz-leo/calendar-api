import httpx


class ApiError(Exception):
    pass


def _request(
    method: str, api_server: str, token: str, path: str, expected_status: int, **kwargs
) -> httpx.Response:
    try:
        response = httpx.request(
            method,
            f"{api_server.rstrip('/')}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            **kwargs,
        )
    except httpx.RequestError as e:
        raise ApiError(f"Could not reach {api_server}: {e}") from e
    if response.status_code != expected_status:
        raise ApiError(f"{api_server} returned {response.status_code}: {response.text}")
    return response


def fetch_events(api_server: str, token: str) -> list[dict]:
    return _request("GET", api_server, token, "/events", 200).json()


def create_event(api_server: str, token: str, payload: dict) -> dict:
    return _request("POST", api_server, token, "/events", 201, json=payload).json()


def update_event(api_server: str, token: str, event_id: str, payload: dict) -> dict:
    return _request("PATCH", api_server, token, f"/events/{event_id}", 200, json=payload).json()


def delete_event(api_server: str, token: str, event_id: str) -> None:
    _request("DELETE", api_server, token, f"/events/{event_id}", 204)
