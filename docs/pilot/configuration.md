# Pilot Configuration Reference

This guide documents the complete pilot configuration parameters for nanobot.

## Configuration Schema

```json
{
  "pilot": {
    "enabled": true,
    "hmac_secret": "your_secure_random_hmac_secret_here",
    "product_consent_version": "pilot-product-v1",
    "training_consent_version": "pilot-training-v1",
    "db_path": "~/.nanobot/pilot_events.db",
    "queue_capacity": 1000,
    "retention_days": 90,
    "max_prompt_chars": 4096,
    "max_reasoning_chars": 8192,
    "max_answer_chars": 8192,
    "flush_timeout_seconds": 5.0
  }
}
```

## Security & Gate Rules

1. **HMAC Secret**: Must be set to a non-empty secret string. Used for domain-separated HMAC-SHA256 identity pseudonymization (`user` and `session` pseudonyms).
2. **Provider Capture Policy**: One of `metrics_only`, `answer`, or `reasoning`. When set to `metrics_only`, no text artifacts are stored regardless of user consent settings.
3. **User Consent**: Scoped via `/consent product on|off` and `/consent training on|off`.
