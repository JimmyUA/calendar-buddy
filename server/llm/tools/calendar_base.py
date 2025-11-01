from langchain_core.tools import BaseTool


class CalendarBaseTool(BaseTool):
    user_id: int
    user_timezone_str: str  # IANA timezone string

    def _run(self, *args, **kwargs): raise NotImplementedError("Sync execution not supported")

