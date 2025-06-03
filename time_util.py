import platform
from datetime import datetime


def format_to_nice_date(iso_date: str) -> str:
    """Return a human friendly date string for the given ISO timestamp."""
    dt = datetime.fromisoformat(iso_date)

    # Format day of month without a leading zero in a portable way.  Using
    # ``dt.day`` avoids the ``%-d`` strftime modifier which is not available on
    # every platform (notably some BSD and Windows variants).
    day = dt.day

    weekday = dt.strftime("%A")
    month_year = dt.strftime("%B %Y")
    time_part = dt.strftime("%H:%M")

    return f"{weekday}, {day} {month_year} · {time_part}"
