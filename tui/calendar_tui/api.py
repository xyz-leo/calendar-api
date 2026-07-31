import httpx


class ApiError(Exception):
    pass


def fetch_events(api_server: str, token: str) -> list[dict]:
    try:
        response = httpx.get(
            f"{api_server.rstrip('/')}/events",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.RequestError as e:
        raise ApiError(f"Could not reach {api_server}: {e}") from e
    if response.status_code != 200:
        raise ApiError(f"{api_server} returned {response.status_code}: {response.text}")
    return response.json()
