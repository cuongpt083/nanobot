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


def test_classify_multistep_query() -> None:
    classifier = TaskComplexityClassifier(threshold=0.5)
    decision, score = classifier.classify("Step 1: download file. Step 2: process it.")

    assert decision == "complex"
    assert score >= 0.5
