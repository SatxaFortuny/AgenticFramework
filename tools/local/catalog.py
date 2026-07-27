"""Single lookup table from a manifest tool ref (a plain string) to the
function that builds that Tool.

Naming convention for refs, enforced by convention rather than code:
    shared.<name>          -> defined in tools/local/shared/
    apps.<app_id>.<name>   -> defined in tools/local/apps/<app_id>/

This is the only file that needs to change when a new local tool is
added anywhere in the framework -- app manifests then opt into it by
key, they never import tool modules directly.
"""

from typing import Callable

from core.interfaces import Retriever
from core.types import Tool

from tools.local.apps.fetchly_docs.search_docs import build_search_fetchly_docs_tool
from tools.local.shared.time_tools import build_current_time_tool

ToolBuilder = Callable[[Retriever | None], Tool]


def _shared_get_current_time(retriever: Retriever | None) -> Tool:
    return build_current_time_tool()


def _apps_fetchly_docs_search_fetchly_docs(retriever: Retriever | None) -> Tool:
    if retriever is None:
        raise ValueError("search_fetchly_docs requires a retriever, none was provided")
    return build_search_fetchly_docs_tool(retriever)


TOOL_CATALOG: dict[str, ToolBuilder] = {
    "shared.get_current_time": _shared_get_current_time,
    "apps.fetchly_docs.search_fetchly_docs": _apps_fetchly_docs_search_fetchly_docs,
}
