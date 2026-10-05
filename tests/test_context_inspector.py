import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from nanobot.agent.inspector import (
    estimate_text_tokens,
    decompose_system_prompt,
    ContextInspectorStore,
)

class TestContextInspector(unittest.TestCase):
    def test_estimate_text_tokens(self):
        self.assertEqual(estimate_text_tokens(""), 0)
        self.assertEqual(estimate_text_tokens("abcd"), 1)
        self.assertEqual(estimate_text_tokens("a" * 100), 25)

    def test_decompose_system_prompt(self):
        prompt = "# Identity\nI am nanobot.\n\n# Tool Contract\nUse tools wisely.\n\n# Memory\nSome memory."
        sections = decompose_system_prompt(prompt)
        self.assertEqual(len(sections), 3)
        self.assertEqual(sections[0].key, "identity")
        self.assertEqual(sections[0].label, "Identity")
        self.assertEqual(sections[1].key, "tool_contract")
        self.assertEqual(sections[2].key, "memory")

    def test_system_prompt_exclusion_preserves_remaining_text(self):
        prompt = "## Identity\nI am nanobot.\nLine 2.\n\n### Skills\nSkill A\nSkill B\n\n# Rules\nRule 1"
        with TemporaryDirectory() as tmpdir:
            store = ContextInspectorStore(storage_dir=Path(tmpdir))
            store.set_exclusions(session_key="test:sys_ex", system_sections=["skills"])
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "hi"},
            ]
            filtered, _ = store.apply_rules(
                session_key="test:sys_ex",
                messages=messages,
                tools_definitions=None,
            )
            expected = "## Identity\nI am nanobot.\nLine 2.\n\n# Rules\nRule 1"
            self.assertEqual(filtered[0]["content"], expected)

    def test_store_record_and_get(self):
        with TemporaryDirectory() as tmpdir:
            store = ContextInspectorStore(storage_dir=Path(tmpdir))
            messages = [
                {"role": "system", "content": "# Identity\nI am bot."},
                {"role": "user", "content": "Hello!"},
                {"role": "assistant", "content": "Hi there!"},
            ]
            tools = [{"name": "read_file", "description": "Reads a file"}]
            snap = store.record_snapshot(
                session_key="test:session",
                messages=messages,
                tools_definitions=tools,
                model_id="test-model",
                provider="test-provider",
                context_window_tokens=128000,
            )
            self.assertTrue(snap.available)
            self.assertIsNotNone(snap.budget)
            self.assertEqual(snap.budget.model_id, "test-model")
            self.assertEqual(snap.budget.max, 128000)
            self.assertEqual(len(snap.system["sections"]), 1)
            self.assertEqual(len(snap.tools["items"]), 1)
            self.assertEqual(len(snap.messages["items"]), 2)

            retrieved = store.get_snapshot("test:session")
            self.assertEqual(retrieved.session_key, "test:session")
            self.assertTrue(retrieved.available)

    def test_rules_and_exclusions(self):
        with TemporaryDirectory() as tmpdir:
            store = ContextInspectorStore(storage_dir=Path(tmpdir))
            store.set_exclusions(
                session_key="test:session2",
                tools=["bad_tool"],
                message_idx=[1],
            )
            rules = store.get_rules("test:session2")
            self.assertEqual(rules["tools"], ["bad_tool"])
            self.assertEqual(rules["message_idx"], [1])

            messages = [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Bad user message"},
                {"role": "assistant", "content": "Assistant message"},
                {"role": "user", "content": "Latest user prompt"},
            ]
            tools = [{"name": "bad_tool"}, {"name": "good_tool"}]
            filtered_msgs, filtered_tools = store.apply_rules(
                session_key="test:session2",
                messages=messages,
                tools_definitions=tools,
            )
            self.assertEqual(len(filtered_msgs), 3)
            self.assertEqual(filtered_msgs[0]["role"], "system")
            self.assertEqual(filtered_msgs[1]["content"], "Assistant message")
            self.assertEqual(filtered_msgs[2]["content"], "Latest user prompt")
            self.assertEqual(len(filtered_tools), 1)
            self.assertEqual(filtered_tools[0]["name"], "good_tool")

    def test_atomic_tool_roundtrip_dropping(self):
        """Verify that dropping an assistant tool_call also drops matching tool result (avoid 400)."""
        with TemporaryDirectory() as tmpdir:
            store = ContextInspectorStore(storage_dir=Path(tmpdir))
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "do something"},
                {"role": "assistant", "content": "calling", "tool_calls": [{"id": "toolu_xyz"}]},
                {"role": "tool", "content": "file output", "tool_call_id": "toolu_xyz"},
                {"role": "assistant", "content": "final answer"},
                {"role": "user", "content": "latest user request"},
            ]
            # Exclude message index 2 (assistant tool call)
            store.set_exclusions(session_key="test:atomic", message_idx=[2])
            filtered_msgs, _ = store.apply_rules(
                session_key="test:atomic",
                messages=messages,
                tools_definitions=None,
            )
            # Both assistant tool_calls (idx 2) AND tool result (idx 3) must be dropped
            roles = [m["role"] for m in filtered_msgs]
            self.assertEqual(roles, ["system", "user", "assistant", "user"])
            self.assertEqual(filtered_msgs[2]["content"], "final answer")

    def test_mark_wasted(self):
        with TemporaryDirectory() as tmpdir:
            store = ContextInspectorStore(storage_dir=Path(tmpdir))
            out = store.mark_wasted(
                session_key="test:wasted",
                ids=["toolu_123"],
            )
            self.assertEqual(out["marked"], 1)
            self.assertEqual(out["total_wasted"], 1)

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "prompt"},
                {"role": "assistant", "content": "calling", "tool_calls": [{"id": "toolu_123"}]},
                {"role": "tool", "content": "result", "tool_call_id": "toolu_123"},
                {"role": "assistant", "content": "final answer"},
                {"role": "user", "content": "next"},
            ]
            filtered_msgs, _ = store.apply_rules(
                session_key="test:wasted",
                messages=messages,
                tools_definitions=None,
            )
            roles = [m["role"] for m in filtered_msgs]
            self.assertEqual(roles, ["system", "user", "assistant", "user"])
            self.assertEqual(filtered_msgs[2]["content"], "final answer")

if __name__ == "__main__":
    unittest.main()
