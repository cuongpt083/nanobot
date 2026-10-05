"""Tests for question routing from Pi bridge extension to coordinator."""

import asyncio

import pytest

from nanobot.coworker.coding.pi.questions import QuestionRouter


@pytest.mark.asyncio
async def test_question_router_basic_flow():
    created_questions = []

    def on_created(q):
        created_questions.append(q)

    router = QuestionRouter(default_timeout_s=5.0, user_timeout_s=30.0, on_question_created=on_created)

    async def simulate_incoming():
        return await router.handle_extension_ui_request(
            request_id="q-1",
            task_id="task-100",
            method="input",
            title="nanobot:ask:api_choice",
            message="Which API version to use?",
        )

    task = asyncio.create_task(simulate_incoming())
    await asyncio.sleep(0.01)

    assert len(created_questions) == 1
    assert created_questions[0].blocking_reason == "api_choice"

    # Answer it
    ok = router.answer_question("q-1", "Use v2 API")
    assert ok is True

    result = await task
    assert result == {"confirmed": True, "value": "Use v2 API"}


@pytest.mark.asyncio
async def test_question_router_escalate_and_timeout():
    router = QuestionRouter(default_timeout_s=0.05, user_timeout_s=0.2)

    task = asyncio.create_task(
        router.handle_extension_ui_request(
            request_id="q-2",
            task_id="task-101",
            method="input",
            title="nanobot:ask:db_choice",
            message="Postgres or SQLite?",
        )
    )
    await asyncio.sleep(0.01)

    # Escalate to user
    ok = router.escalate_to_user("q-2")
    assert ok is True
    q = router.get_pending("q-2")
    assert q.escalated is True

    # After original default timeout (0.05), should NOT have timed out yet
    await asyncio.sleep(0.06)
    assert not task.done()

    # Answer before user timeout
    router.answer_question("q-2", "SQLite")
    result = await task
    assert result["confirmed"] is True
    assert result["value"] == "SQLite"


@pytest.mark.asyncio
async def test_question_router_unrelated_dialog():
    router = QuestionRouter()
    result = await router.handle_extension_ui_request(
        request_id="q-3",
        task_id="task-102",
        method="input",
        title="Unrelated prompt",
        message="some prompt",
    )
    assert result == {"cancelled": True}


@pytest.mark.asyncio
async def test_question_router_cleanup_on_cancel():
    router = QuestionRouter()

    async def _call():
        return await router.handle_extension_ui_request(
            request_id="q-4",
            task_id="task-103",
            method="input",
            title="nanobot:ask:test_reason",
            message="some question",
        )

    task = asyncio.create_task(_call())
    await asyncio.sleep(0.01)
    assert "q-4" in router._waiters
    assert "q-4" in router._timers

    router.cancel_question("q-4")
    res = await task
    assert res == {"cancelled": True}
    assert "q-4" not in router._waiters
    assert "q-4" not in router._timers
