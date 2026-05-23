import re
from typing import Annotated, Dict, Union

from agent_framework import tool


CATEGORY_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "Battery Issue": ("battery", "charge", "swelling", "overheat", "power"),
    "Screen Issue": ("screen", "display", "pixel", "glass", "lcd", "touch"),
    "Connectivity Issue": ("wifi", "bluetooth", "lte", "signal", "network", "connection", "connectivity"),
    "Performance Issue": ("slow", "lag", "freeze", "crash", "performance"),
    "Software Update": ("update", "patch", "firmware", "install"),
    "Audio Issue": ("speaker", "microphone", "audio", "sound", "volume"),
}


def classify_issue(customer_message: str) -> Dict[str, Union[str, float]]:
    """
    Lightweight classifier that maps a complaint to an issue category.

    :param customer_message: Raw customer complaint text to classify.
    :return: Mapping with ``category`` and ``confidence`` keys derived from keyword matches.
    """

    normalized = customer_message.lower()
    category = "General Inquiry"
    confidence = 0.1

    for label, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if re.search(rf"\b{re.escape(keyword)}\b", normalized))
        if hits > 0 and hits / len(keywords) > confidence:
            category = label
            confidence = min(0.9, hits / len(keywords) + 0.3)

    return {"category": category, "confidence": round(confidence, 2)}


@tool(
    name="classify_issue",
    description="Classify a customer complaint into a support category and return a confidence percentage.",
)
def classify_issue_tool(
    customer_message: Annotated[str, "The customer complaint text to triage."]
) -> Dict[str, Union[str, float]]:
    """Expose the lightweight classifier as an Agent Framework tool."""

    return classify_issue(customer_message)


__all__ = ["classify_issue", "classify_issue_tool"]
