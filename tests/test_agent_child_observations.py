from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import agent as agent_module


class FakeObservation:
    def __init__(self, kwargs: dict) -> None:
        self.kwargs = kwargs
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


@pytest.fixture()
def recorded(monkeypatch):
    observations: list[FakeObservation] = []

    @contextmanager
    def fake_start_observation(**kwargs):
        obs = FakeObservation(kwargs)
        observations.append(obs)
        yield obs

    monkeypatch.setattr(agent_module, "start_observation", fake_start_observation)
    return observations


def test_retrieval_is_a_retriever_child_observation(recorded) -> None:
    docs = agent_module.LabAgent()._retrieve("What is your refund policy? mail a@b.com")

    assert docs
    obs = recorded[0]
    assert obs.kwargs["name"] == "retrieval"
    assert obs.kwargs["as_type"] == "retriever"
    assert "a@b.com" not in str(obs.kwargs["input"])
    assert obs.updates[-1]["output"] == {"doc_count": len(docs)}


def test_retrieval_failure_marks_observation_as_error(recorded, monkeypatch) -> None:
    def boom(_: str):
        raise RuntimeError("Vector store timeout")

    monkeypatch.setattr(agent_module, "retrieve", boom)

    with pytest.raises(RuntimeError):
        agent_module.LabAgent()._retrieve("x")

    assert recorded[0].updates[-1]["level"] == "ERROR"


def test_generation_records_model_usage_and_cost(recorded) -> None:
    agent = agent_module.LabAgent()

    response, cost_usd = agent._generate("Feature=qa\nDocs=x\nQuestion=hello a@b.com")

    obs = recorded[0]
    assert obs.kwargs["as_type"] == "generation"
    assert obs.kwargs["model"] == agent.model
    assert "a@b.com" not in obs.kwargs["input"]
    update = obs.updates[-1]
    assert update["usage_details"] == {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
    }
    assert update["cost_details"]["total"] == cost_usd
    assert cost_usd == agent._estimate_cost(response.usage.input_tokens, response.usage.output_tokens)
