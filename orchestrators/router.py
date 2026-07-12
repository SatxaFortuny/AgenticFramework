from core.interfaces import Orchestrator
from core.types import RunContext, RunResult

SYSTEM_PROMPT = """You are an assistant for the Fetchly HTTP client \
library. You have tools available -- use them ONLY when the user asks \
something that requires looking up documentation or real-time \
information you don't already know. For greetings, small talk, or \
questions that don't require a tool, answer directly without calling \
any tool. Do not guess at documentation details; use the search tool \
instead of inventing an answer.
"""


class RouterOrchestrator(Orchestrator):
    def run(self, query: str, context: RunContext) -> RunResult:
        if context.tools is None:
            raise ValueError("RouterOrchestrator requires a ToolProvider in RunContext")

        tools = context.tools.list_tools()
        tool_specs = [t.spec for t in tools]

        first_response = context.model.generate(
            SYSTEM_PROMPT, query, tools=tool_specs
        )

        trace = [
            {
                "step": "route",
                "query": query,
                "tools_offered": [t.name for t in tool_specs],
                "tool_calls_requested": [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in first_response.tool_calls
                ],
            }
        ]

        if not first_response.tool_calls:
            trace.append({"step": "direct_answer"})
            return RunResult(answer=first_response.text, trace=trace)

        tool_results = []
        for call in first_response.tool_calls:
            result = context.tools.call_tool(call.name, call.arguments)
            tool_results.append(result)
            trace.append(
                {
                    "step": "tool_call",
                    "name": call.name,
                    "arguments": call.arguments,
                    "output": result.output,
                }
            )

        results_text = "\n\n".join(
            f"[{r.name} result]\n{r.output}" for r in tool_results
        )
        follow_up_message = (
            f"Question: {query}\n\nTool results:\n{results_text}\n\n"
            "Using the tool results above, answer the original question."
        )
        final_response = context.model.generate(SYSTEM_PROMPT, follow_up_message)

        trace.append({"step": "final_generate", "user_message": follow_up_message})

        return RunResult(answer=final_response.text, trace=trace)