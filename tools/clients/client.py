import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_ollama import ChatOllama

client = MultiServerMCPClient(
    {
        "server1": {
            "url": "http://localhost:8000/sse",
            "transport": "sse",
        }
    }
)

async def test():
    tools = await client.get_tools()
    ollama = ChatOllama(model="llama3.1:8b")
    agent = create_react_agent(ollama, tools)
    response = await agent.ainvoke({"messages": "Which is Satxa's favorite fruit?"})
    return response["messages"][-1].content

result = asyncio.run(test())
print(result)