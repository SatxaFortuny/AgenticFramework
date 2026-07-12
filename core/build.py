from adapters.local_tools import LocalToolRegistry
from adapters.naive_retriever import NaiveRetriever
from adapters.ollama_provider import OllamaProvider
from core.types import RunContext
from docs import DOCUMENTS
from orchestrators.router import RouterOrchestrator
from orchestrators.sequential import SequentialOrchestrator


def build_default_pipeline():
    model = OllamaProvider(model="llama3.2")
    retriever = NaiveRetriever(DOCUMENTS)
    orchestrator = SequentialOrchestrator(k=2)
    context = RunContext(model=model, retriever=retriever)
    return orchestrator, context


def build_router_pipeline():
    model = OllamaProvider(model="llama3.2")
    retriever = NaiveRetriever(DOCUMENTS)
    tools = LocalToolRegistry(retriever=retriever)
    orchestrator = RouterOrchestrator()
    context = RunContext(model=model, tools=tools)
    return orchestrator, context
