import datetime

__all__ = ["isoparse"]


def isoparse(date_string: str) -> datetime.datetime:
    """Parse an ISO formatted date string using the standard library."""
    if date_string.endswith("Z"):
        date_string = date_string[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(date_string)
