from __future__ import annotations

TOOL_KIND_MAP: dict[str, str] = {
    "classify_issue": "read",
    "search_similar_complaints": "retrieve",
    "retrieve_docs": "read",
    "create_ticket": "ticket",
    "notify_team": "notify",
}


def get_tool_kind(tool_name: str) -> str:
    return TOOL_KIND_MAP.get(tool_name, "other")
