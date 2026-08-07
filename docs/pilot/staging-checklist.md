# Pilot Staging Readiness Checklist

- [ ] All automated tests in `tests/pilot/` are green (`uv run pytest tests/pilot -q`).
- [ ] WebUI tests pass (`bun run test`).
- [ ] Ruff check and type checks pass (`uv run ruff check nanobot tests` and `uv run basedpyright`).
- [ ] HMAC secret is configured to a non-default secret string.
- [ ] Endpoint health check `/api/pilot/health` returns `200 OK` with student status `"ok"`.
- [ ] Operational metrics `/api/pilot/metrics` returns non-sensitive metrics.
- [ ] 72-hour staging run completes with zero reasoning canary leaks.
- [ ] Student SLM model binary exists at `~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf`.
- [ ] Simple queries route to `student` route_class and complex queries trigger Teacher review plan.
