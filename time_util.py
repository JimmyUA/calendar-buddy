import platform
from datetime import datetime


def format_to_nice_date(iso_date: str) -> str:
    dt = datetime.fromisoformat(iso_date)
    if platform.system() == "Windows":
        # Windows doesn't support %-d, use %d and strip leading zero if present
        day_str = dt.strftime("%d")
        if day_str.startswith('0'):
            day_str = day_str[1:]
        return dt.strftime(f"%A, {day_str} %B %Y · %H:%M")
    else:
        # Unix-like systems
        return dt.strftime("%A, %-d %B %Y · %H:%M")