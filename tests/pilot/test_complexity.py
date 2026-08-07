"""Tests for TaskComplexityClassifier."""

from nanobot.pilot.complexity import TaskComplexityClassifier


def test_classify_simple_query() -> None:
    classifier = TaskComplexityClassifier(threshold=0.5)
    decision, score = classifier.classify("Hello, how are you?")

    assert decision == "simple"
    assert score < 0.5


def test_classify_code_query() -> None:
    classifier = TaskComplexityClassifier(threshold=0.5)
    decision, score = classifier.classify("Write a python function ```def foo(): pass```")

    assert decision == "complex"
    assert score >= 0.5


def test_classify_required_tools() -> None:
    classifier = TaskComplexityClassifier(threshold=0.5)
    # Simple query with required tool should be complex
    decision, score = classifier.classify("Run command", required_tools=["bash"])
    assert decision == "complex"
    assert score >= 0.5

    # Simple query without required tools remains simple
    decision_simple, score_simple = classifier.classify("Hello world", required_tools=[])
    assert decision_simple == "simple"
    assert score_simple < 0.5
