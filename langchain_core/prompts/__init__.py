class PromptTemplate:
    @classmethod
    def from_template(cls, template):
        return cls()

class ChatPromptTemplate:
    pass

class MessagesPlaceholder:
    def __init__(self, *a, **k):
        pass

__all__ = ["PromptTemplate", "ChatPromptTemplate", "MessagesPlaceholder"]
