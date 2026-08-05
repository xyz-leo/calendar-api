from fastapi import HTTPException
from googleapiclient.errors import HttpError

# Google's HttpError carries a real, meaningful status — pass the common ones through
# as-is instead of letting every Google hiccup surface as a generic 500. Shared by
# every service that wraps a googleapiclient request object (CalendarService,
# TaskService, ...) since translating a Google API error into a clean HTTPException
# has nothing to do with which Google API raised it.
_STATUS_DETAIL = {
    403: "Google denied this request (check the granted scope/permissions)",
    401: "Google access expired or was revoked — log in with Google again",
}


def execute_google_request(
    request, *, not_found_detail: str = "Resource not found", api_label: str = "Google API"
):
    try:
        return request.execute()
    except HttpError as e:
        status = e.resp.status
        if status == 404:
            detail = not_found_detail
        else:
            detail = _STATUS_DETAIL.get(status, f"{api_label} error ({status})")
        raise HTTPException(
            status_code=status if status in (404, 403, 401) else 502,
            detail=detail,
        )
