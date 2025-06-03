from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .exceptions import UnknownTimeZoneError

class BaseTzInfo(ZoneInfo):
    pass

utc = ZoneInfo("UTC")

def timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as e:
        raise UnknownTimeZoneError(name) from e
