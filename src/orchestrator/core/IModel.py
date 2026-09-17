from abc import ABC, abstractmethod

from langgraph.graph import MessagesState


# The metadata of the conversation
class State(MessagesState):
    extra_field: int
    context: dict[str, list[str]]

class IModel(ABC):
        
    @abstractmethod
    def bind_tools(self, tools: list[any]) -> None:
        pass
        
    @abstractmethod
    def generate(self, state: State, context_id: str | None = None):
        pass
