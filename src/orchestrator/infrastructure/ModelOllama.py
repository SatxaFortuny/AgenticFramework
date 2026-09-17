from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama

from core.IModel import IModel, State


class ModelOllama(IModel):
    
    def __init__(self, model_name: str):
        
        self.llm = ChatOllama(
            model=model_name,
            temperature=0.5
        )

    def bind_tools(self, tools: list[any]) -> None:
        if tools:
            self.llm = self.llm.bind_tools(tools)

    def generate(self, state: State, context_id: str | None = None):
        
        messages = state["messages"]
        context = state.get("context", {})
        if context_id in context:
            context = context[context_id]
            system_instruction = f"Use this as context: {context}"
            messages = [SystemMessage(content=system_instruction)] + messages
            
        response = self.llm.invoke(messages)
        return {"messages": [response]}
