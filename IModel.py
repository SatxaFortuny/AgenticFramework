from langgraph.graph import MessagesState
from abc import ABC, abstractmethod

# The metadata of the conversation
class State(MessagesState):
    extra_field: int

class IModel(ABC):
        
    @abstractmethod
    def generate(self, state: State):
        pass