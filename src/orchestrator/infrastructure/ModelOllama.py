import logging
import time

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama

from core.IModel import IModel, State
from core.logging_utils import elapsed_ms, preview

logger = logging.getLogger(__name__)


class ModelOllama(IModel):
    def __init__(self, model_name: str):

        self.model_name = model_name
        self.llm = ChatOllama(model=model_name, temperature=0.5)
        logger.debug("Initialised ChatOllama model '%s'", model_name)

    def bind_tools(self, tools: list[any]) -> None:
        if tools:
            self.llm = self.llm.bind_tools(tools)
            logger.debug("Bound %d tool(s) to '%s'", len(tools), self.model_name)

    def generate(self, state: State, context_id: str | None = None):

        messages = state["messages"]
        context = state.get("context", {})
        has_context = context_id in context
        if has_context:
            context = context[context_id]
            system_instruction = f"Use this as context: {context}"
            messages = [SystemMessage(content=system_instruction)] + messages
            logger.debug("Injected context: %s", preview(context))

        logger.info(
            "LLM call started (model=%s, messages=%d, with_context=%s)",
            self.model_name,
            len(messages),
            has_context,
        )
        start = time.perf_counter()
        try:
            response = self.llm.invoke(messages)
        except Exception as exc:
            logger.error(
                "LLM call failed after %.0f ms (model=%s): %s",
                elapsed_ms(start),
                self.model_name,
                exc,
            )
            raise

        tool_calls = getattr(response, "tool_calls", None) or []
        logger.info(
            "LLM call finished in %.0f ms (tool_calls=%d)",
            elapsed_ms(start),
            len(tool_calls),
        )
        logger.debug("LLM response: %s", preview(response.content))
        return {"messages": [response]}
