from abc import ABC, abstractmethod

from langgraph.graph import MessagesState


class State(MessagesState):
    """In langraph, different nodes must have a way to communicate or to retain necessary data for further nodes. State is a class that is updated across the whole lifecycle of the graph to provide context to new nodes. The class inheriths from MessagesState which handles the conversation history."""

    # Here a list[str] would suffice but the idea is that across the graph there might be different RAGs and identifying them correctly might be better.
    context: dict[str, list[str]]


class IModel(ABC):
    """In order to maintain swappability, we must declare a contract between this component and the others. By creating a model interface, we make all the model providers have a common ground in order to maintain transparency."""

    @abstractmethod
    def bind_tools(self, tools: list[any]) -> None:
        """bind_tools is used to enable the use of tool calling regardless of the provider. As an argument we have a list of tools, of any type."""

    @abstractmethod
    def generate(self, state: State, context_id: str | None = None):
        """generate is the function that sends the request to the actual model. By passing the state and the context_id we give the precise context needed."""
