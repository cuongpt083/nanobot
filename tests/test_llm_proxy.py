import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nanobot.llm_proxy.budget import BudgetTracker, get_period_key
from nanobot.llm_proxy.keys import KeyStore, ProxyApiKey


class TestLLMProxy(unittest.TestCase):
    def test_period_key_windows(self):
        self.assertTrue(get_period_key("5h").count("T") == 1)
        self.assertTrue(get_period_key("daily").count("-") == 2)
        self.assertTrue("W" in get_period_key("weekly"))
        self.assertEqual(get_period_key("lifetime"), "lifetime")

    def test_keystore_creation_and_validation(self):
        with TemporaryDirectory() as tmpdir:
            store = KeyStore(storage_dir=Path(tmpdir))
            secret, key = store.create_key(
                name="Test Client",
                budget_period="5h",
                budget_tokens=1000,
            )
            self.assertTrue(secret.startswith("sk-nano-"))
            self.assertEqual(key.name, "Test Client")

            # Validate valid secret
            val_key = store.validate_secret(secret)
            self.assertIsNotNone(val_key)
            self.assertEqual(val_key.id, key.id)

            # Validate invalid secret
            self.assertIsNone(store.validate_secret("sk-nano-fake"))

    def test_budget_enforcement(self):
        with TemporaryDirectory() as tmpdir:
            store = KeyStore(storage_dir=Path(tmpdir))
            tracker = BudgetTracker(storage_dir=Path(tmpdir))

            secret, key = store.create_key(
                name="Budget Client",
                budget_period="5h",
                budget_tokens=500,
            )

            # Initial check
            allowed, status = tracker.check_budget(key)
            self.assertTrue(allowed)
            self.assertEqual(status["used"], 0)
            self.assertEqual(status["remaining"], 500)

            # Consume 300 tokens
            tracker.commit_tokens(key, 300)
            allowed, status = tracker.check_budget(key)
            self.assertTrue(allowed)
            self.assertEqual(status["used"], 300)
            self.assertEqual(status["remaining"], 200)

            # Consume 250 tokens (exceeding 500 limit)
            tracker.commit_tokens(key, 250)
            allowed, status = tracker.check_budget(key)
            self.assertFalse(allowed)
            self.assertEqual(status["used"], 550)
            self.assertEqual(status["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
