"""
Router/supervisor Orchestrator: lets the model decide which tool(s) to
call based on the query, executes them via the ToolProvider, then does a
second generation pass with the results to produce the final answer.
Falls straight through to a direct answer if the model calls no tools.
"""

from core.interfaces import Orchestrator
from core.prompts import DEFAULT_ROUTER_PROMPT_VERSION, get_prompt
from core.types import RunContext, RunResult

from typing import Literal
from pydantic import BaseModel

class RouterOrchestratorConfig(BaseModel):
    type: Literal["router"]
    prompt_version: str | None = None

    def build(self):
        kwargs = self.model_dump(exclude={"type"}, exclude_none=True)
        return RouterOrchestrator(**kwargs)

class RouterOrchestrator(Orchestrator):
    def __init__(self, prompt_version: str = DEFAULT_ROUTER_PROMPT_VERSION):
        self.prompt_version = prompt_version

    def run(self, query: str, context: RunContext) -> RunResult:
        if context.tools is None:
            raise ValueError("RouterOrchestrator requires a ToolProvider in RunContext")

        system_prompt = get_prompt(self.prompt_version)
        tools = context.tools.list_tools()
        tool_specs = [t.spec for t in tools]

        first_response = context.model.generate(system_prompt, query, tools=tool_specs)

        trace = [
            {
                "step": "route",
                "prompt_version": self.prompt_version,
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

        results_text = "\n\n".join(f"[{r.name} result]\n{r.output}" for r in tool_results)
        follow_up_message = (
            f"Question: {query}\n\nTool results:\n{results_text}\n\n"
            "Using the tool results above, answer the original question."
        )

        # The routing decision (above) used context.model -- often a
        # fast/cheap model, since deciding which tool to call is a small
        # classification task. The actual answer synthesis can use a
        # stronger model if one was provided, since that's where answer
        # quality actually matters.
        worker = context.worker_model or context.model
        final_response = worker.generate(system_prompt, follow_up_message)

        trace.append({
            "step": "final_generate",
            "used_worker_model": context.worker_model is not None,
            "user_message": follow_up_message,
        })

        return RunResult(answer=final_response.text, trace=trace)
