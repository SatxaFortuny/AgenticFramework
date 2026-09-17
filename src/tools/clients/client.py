import asyncio

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent


async def test():
    client = MultiServerMCPClient(
        {
            "server1": {
                "url": "http://localhost:8000/sse",
                "transport": "sse",
            }
        }
    )
    tools = await client.get_tools()
    ollama = ChatOllama(model="llama3.1:8b")
    agent = create_react_agent(ollama, tools)
    response = await agent.ainvoke({"messages": "Which is Satxa's favorite fruit?"})
    return response["messages"][-1].content


if __name__ == "__main__":
    result = asyncio.run(test())
    print(result)
