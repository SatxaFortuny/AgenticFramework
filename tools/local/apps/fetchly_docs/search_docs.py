"""Local tools specific to the 'fetchly_docs' app.

Anything under tools/local/apps/<app_id>/ is private to that app: it's
only wired in if that app's manifest (tools/configs/apps/<app_id>.yaml)
lists it. Other apps can't reach it, even by name.
"""

from core.interfaces import Retriever
from core.types import Tool, ToolSpec


def build_search_fetchly_docs_tool(retriever: Retriever) -> Tool:
    def handler(arguments: dict) -> str:
        query = arguments.get("query", "")
        chunks = retriever.retrieve(query, k=2)
        if not chunks:
            return "No relevant documentation found."

        parts = []
        for chunk in chunks:
            title = chunk.metadata.get("title", "Untitled")
            parts.append(f"--- {title} ---\n{chunk.content.strip()}")
        return "\n\n".join(parts)

    return Tool(
        spec=ToolSpec(
            name="search_fetchly_docs",
            description=(
                "Search the Fetchly HTTP client library documentation for "
                "information about how to use the library (installation, "
                "timeouts, retries, auth, error handling)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in the docs.",
                    }
                },
                "required": ["query"],
            },
        ),
        handler=handler,
    )
