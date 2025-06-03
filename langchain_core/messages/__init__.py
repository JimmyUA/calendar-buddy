class AIMessage:
    def __init__(self, content=""):
        self.content = content

class HumanMessage:
    def __init__(self, content=""):
        self.content = content

__all__ = ["AIMessage", "HumanMessage"]
