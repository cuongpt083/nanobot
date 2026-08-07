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
    "flush_timeout_seconds": 5.0,
    "student": {
      "enabled": true,
      "model_path": "~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf",
      "context_length": 4096,
      "max_tokens": 2048,
      "temperature": 0.7,
      "concurrent_instances": 1,
      "complexity_threshold": 0.5,
      "teacher_provider": "deepseek",
      "llama_cpp_path": "~/.nanobot/llama.cpp/"
    }
  }
}
```

## Security & Gate Rules

1. **HMAC Secret**: Must be set to a non-empty secret string. Used for domain-separated HMAC-SHA256 identity pseudonymization (`user` and `session` pseudonyms).
2. **Provider Capture Policy**: One of `metrics_only`, `answer`, or `reasoning`. When set to `metrics_only`, no text artifacts are stored regardless of user consent settings.
3. **User Consent**: Scoped via `/consent product on|off` and `/consent training on|off`.
4. **Student SLM Routing**: When `pilot.student.enabled` is `true`, simple queries (score < `complexity_threshold`) are routed directly to the SLM, while complex queries trigger SLM step-by-step planning under Teacher LLM review.
