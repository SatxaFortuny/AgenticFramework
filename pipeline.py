from langchain_core.messages import AnyMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.checkpoint.memory import InMemorySaver
from langchain_ollama import ChatOllama
import uuid
from IModel import IModel, State
from ModelOllama import ModelOllama

# In order to dynamically choose the model, I have to wrap the node function. That is because the node function only accepts state as an argument.
def create_node(model: IModel):
    def node(state: State):
        response = model.generate(state)
        return {"messages": [response], "extra_field": 10}
    return node
    
# Models initialization
ollama = ModelOllama(model_name="llama3.1:8b")
    
# The graph builder
builder = StateGraph(State)
ollama_node = create_node(ollama)
builder.add_node("node1", ollama_node)
builder.add_edge(START, "node1")

# The checkpointer is the one that saves the state
checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

conversation_id = str(uuid.uuid4())
print(f"Coversation id: {conversation_id}")
config = {"configurable": {"thread_id": conversation_id}}

result = graph.invoke({"messages": [HumanMessage("Hi")]}, config)
print(result["messages"][-1].content)