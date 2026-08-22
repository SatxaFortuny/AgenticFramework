from IModel import IModel, State
from langchain_ollama import ChatOllama

class ModelOllama(IModel):
    
    def __init__(self, model_name: str):
        
        self.llm = ChatOllama(
            model=model_name,
            temperature=0.5
        )

    def generate(self, state: State):
        
        messages = state["messages"]
        response = self.llm.invoke(messages)
        return response