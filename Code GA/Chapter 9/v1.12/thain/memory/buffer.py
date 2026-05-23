from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable, Optional


@dataclass
class ComplaintRecord:
    """Represents a single customer complaint captured by Thain."""

    message: str
    category: str
    summary: str


class ConversationMemory:
    """Simple bounded in-memory store for recent complaints."""

    def __init__(self, capacity: int = 5) -> None:
        if capacity <= 0:
            raise ValueError("Memory capacity must be greater than zero.")
        self._records: Deque[ComplaintRecord] = deque(maxlen=capacity)

    def add(self, record: ComplaintRecord) -> None:
        """Append a complaint to memory."""

        self._records.append(record)

    def records(self) -> Iterable[ComplaintRecord]:
        """Return an iterable view over stored complaints."""

        return tuple(self._records)

    def contextual_instructions(self) -> Optional[str]:
        """Render memory into a string the agent can consume as extra guidance."""

        if not self._records:
            return None

        lines = [
            "- {category}: {summary}".format(category=entry.category, summary=entry.summary)
            for entry in self._records
        ]
        return "Recent customer complaints to keep in mind:\n" + "\n".join(lines)

