# Provider Failover & Circuit Breaker Runbook

## Circuit Breaker Architecture

- Model-scoped circuit breaking tracks error rates per provider model.
- Cooldown period automatically isolates failing providers and routes traffic to configured fallbacks.
- Single answer fallback guarantees one final response is delivered to the user even during provider failure.
