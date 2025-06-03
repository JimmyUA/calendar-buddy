from .render import render_text_description

class BaseTool:
    def __init__(self, *a, **k):
        pass

__all__ = ["render_text_description", "BaseTool"]
