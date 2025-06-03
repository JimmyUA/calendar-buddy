from datetime import datetime

__all__ = ["relativedelta"]

class relativedelta:
    def __init__(self, end: datetime, start: datetime):
        if end < start:
            end, start = start, end
        delta = end - start
        self.years = 0
        self.months = 0
        self.days = delta.days
        self.hours, rem = divmod(delta.seconds, 3600)
        self.minutes, self.seconds = divmod(rem, 60)
