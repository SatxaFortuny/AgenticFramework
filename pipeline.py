from langchain_core.messages import AnyMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.checkpoint.memory import InMemorySaver
from langchain_ollama import ChatOllama
import uuid

llm = ChatOllama(
    model="llama3.1:8b",
    temperature=0.5
)

# The metadata of the conversation
class State(MessagesState):
    extra_field: int
   
# The action 
def node(state: State):
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response], "extra_field": 10}
    
# The graph builder
builder = StateGraph(State)
builder.add_node("node1", node)
builder.add_edge(START, "node1")

# The checkpointer is the one that saves the state
checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

conversation_id = str(uuid.uuid4())
print(f"Coversation id: {conversation_id}")
config = {"configurable": {"thread_id": conversation_id}}

result = graph.invoke({"messages": [HumanMessage("Hi")]}, config)
print(result["messages"][-1].content)