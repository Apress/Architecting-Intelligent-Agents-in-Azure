"""
Chapter 2 unit tests — MAF 1.5.0 GA.

Covers all testable units without requiring an Azure connection:
- Keyword classifier logic
- ConversationMemory and ComplaintRecord
- MemoryContextProvider (GA ContextProvider interface)
- parse_structured_response
- _extract_latest_role_text (DevUI helper)
"""

import asyncio
import json
import unittest
from unittest.mock import MagicMock

from agent_framework import Message

from memory.buffer import ComplaintRecord, ConversationMemory
from tools.classifier import classify_issue, classify_issue_tool
from main import (
    MemoryContextProvider,
    _extract_latest_role_text,
    parse_structured_response,
    update_memory,
    memory_store,
)


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

class ClassifierTests(unittest.TestCase):
    def test_battery_category(self) -> None:
        result = classify_issue("My phone battery is swelling and won't charge.")
        self.assertEqual(result["category"], "Battery Issue")
        self.assertGreater(result["confidence"], 0.1)

    def test_connectivity_category(self) -> None:
        result = classify_issue("WiFi keeps dropping whenever I walk around.")
        self.assertEqual(result["category"], "Connectivity Issue")

    def test_screen_category(self) -> None:
        result = classify_issue("The screen has dead pixels and the display flickers.")
        self.assertEqual(result["category"], "Screen Issue")

    def test_unknown_falls_back_to_general(self) -> None:
        result = classify_issue("I just wanted to say thank you.")
        self.assertEqual(result["category"], "General Inquiry")
        self.assertAlmostEqual(result["confidence"], 0.1)

    def test_tool_wraps_classifier(self) -> None:
        result = classify_issue_tool("The speaker is crackling at high volume.")
        self.assertEqual(result["category"], "Audio Issue")

    def test_tool_has_correct_name(self) -> None:
        self.assertEqual(classify_issue_tool.name, "classify_issue")


# ---------------------------------------------------------------------------
# ConversationMemory tests
# ---------------------------------------------------------------------------

class ConversationMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = ConversationMemory(capacity=3)

    def test_add_and_retrieve(self) -> None:
        self.memory.add(ComplaintRecord(message="msg", category="Battery Issue", summary="Battery swelling"))
        records = list(self.memory.records())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, "Battery Issue")

    def test_capacity_evicts_oldest(self) -> None:
        for i in range(4):
            self.memory.add(ComplaintRecord(message=f"msg{i}", category=f"Cat{i}", summary=f"Sum{i}"))
        records = list(self.memory.records())
        self.assertEqual(len(records), 3)
        # Oldest (Cat0) should be gone
        categories = [r.category for r in records]
        self.assertNotIn("Cat0", categories)

    def test_empty_memory_returns_none_instructions(self) -> None:
        self.assertIsNone(self.memory.contextual_instructions())

    def test_contextual_instructions_format(self) -> None:
        self.memory.add(ComplaintRecord(message="m", category="Screen Issue", summary="Cracked screen"))
        instructions = self.memory.contextual_instructions()
        self.assertIsNotNone(instructions)
        self.assertIn("Screen Issue", instructions)
        self.assertIn("Cracked screen", instructions)

    def test_invalid_capacity_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConversationMemory(capacity=0)


# ---------------------------------------------------------------------------
# MemoryContextProvider (GA interface) tests
# ---------------------------------------------------------------------------

class MemoryContextProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.memory = ConversationMemory(capacity=5)
        self.provider = MemoryContextProvider(self.memory)

    def test_source_id_set(self) -> None:
        self.assertEqual(self.provider.source_id, "memory")

    async def test_before_run_empty_memory_adds_no_instructions(self) -> None:
        context = MagicMock()
        context.instructions = []
        await self.provider.before_run(agent=None, session=None, context=context, state={})
        self.assertEqual(context.instructions, [])

    async def test_before_run_with_memory_appends_instructions(self) -> None:
        self.memory.add(ComplaintRecord(message="m", category="Connectivity Issue", summary="WiFi drops"))
        context = MagicMock()
        context.instructions = []
        await self.provider.before_run(agent=None, session=None, context=context, state={})
        self.assertEqual(len(context.instructions), 1)
        self.assertIn("Connectivity Issue", context.instructions[0])


# ---------------------------------------------------------------------------
# parse_structured_response tests
# ---------------------------------------------------------------------------

class ParseStructuredResponseTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        raw = '{"category": "Battery Issue", "summary": "Battery swelling."}'
        result = parse_structured_response(raw)
        self.assertEqual(result["category"], "Battery Issue")

    def test_json_in_code_fence(self) -> None:
        raw = '```json\n{"category": "Screen Issue", "summary": "Cracked screen."}\n```'
        result = parse_structured_response(raw)
        self.assertEqual(result["category"], "Screen Issue")

    def test_json_embedded_in_text(self) -> None:
        raw = 'Here is the result: {"category": "Audio Issue", "summary": "Speaker crackling."} done.'
        result = parse_structured_response(raw)
        self.assertEqual(result["category"], "Audio Issue")

    def test_invalid_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_structured_response("This is not JSON at all.")


# ---------------------------------------------------------------------------
# _extract_latest_role_text (DevUI helper) tests
# ---------------------------------------------------------------------------

class ExtractRoleTextTests(unittest.TestCase):
    def test_string_user_role(self) -> None:
        result = _extract_latest_role_text("hello", "user")
        self.assertEqual(result, "hello")

    def test_string_non_user_role_returns_none(self) -> None:
        result = _extract_latest_role_text("hello", "assistant")
        self.assertIsNone(result)

    def test_none_input_returns_none(self) -> None:
        self.assertIsNone(_extract_latest_role_text(None, "user"))

    def test_message_object_matching_role(self) -> None:
        msg = Message("user", ["customer complaint"])
        result = _extract_latest_role_text(msg, "user")
        self.assertEqual(result, "customer complaint")

    def test_message_object_non_matching_role(self) -> None:
        msg = Message("assistant", ["response text"])
        result = _extract_latest_role_text(msg, "user")
        self.assertIsNone(result)

    def test_list_returns_latest_matching(self) -> None:
        msgs = [
            Message("user", ["first message"]),
            Message("assistant", ["response"]),
            Message("user", ["second message"]),
        ]
        result = _extract_latest_role_text(msgs, "user")
        self.assertEqual(result, "second message")


if __name__ == "__main__":
    unittest.main()
