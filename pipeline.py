from langchain_core.messages import AnyMessage, AIMessage, HumanMessage
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, MessagesState

class State(MessagesState):
    extra_field: int
    
def node(state: State):
    messages = state["messages"]
    new_message = AIMessage("Hello!")
    return {"messages": messages + [new_message], "extra_field": 10}
    
builder = StateGraph(State)
builder.add_node(node)
builder.set_entry_point("node")
graph = builder.compile()
result = graph.invoke({"messages": [HumanMessage("Hi")]})
print(result)