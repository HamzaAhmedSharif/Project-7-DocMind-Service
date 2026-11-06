"""Unit tests for the capacity model pure function (Master Script 10.3),
on fixed numbers worked out by hand."""

import pytest

from evaluation.capacity_model import capacity

INPUTS = {
    "mean_prompt_tokens": 2000.0,
    "mean_completion_tokens": 500.0,
    "tpm": 8000,
    "rpm": 30,
    "rpd": 1000,
    "tpd": 200_000,
    "calls_per_query": 1,
    "global_cap": 800,
    "mean_api_seconds": 30.0,
    "cache_scenarios": {"h=0": 0.0, "h=0.5": 0.5},
    "multi_token_ratio": 2.0,
    "multi_call_factor": 3.1,
}


def test_tokens_and_qpm():
    out = capacity(INPUTS)
    assert out["tokens_per_query"] == 2500.0
    assert out["qpm_tokens"] == pytest.approx(0.9 * 8000 / 2500)
    assert out["qpm_requests"] == pytest.approx(27.0)
    assert out["qpm"] == pytest.approx(0.9 * 8000 / 2500)


def test_daily_is_tpd_bound():
    out = capacity(INPUTS)
    # min(1000 requests, 800 global cap, 200000 / 2500 = 80 by tokens)
    assert out["daily_provider_bound_answered"] == pytest.approx(80.0)
    assert out["served_per_day_scenarios"]["h=0"] == pytest.approx(80.0)
    assert out["served_per_day_scenarios"]["h=0.5"] == pytest.approx(160.0)


def test_littles_law_and_multi_agent():
    out = capacity(INPUTS)
    assert out["in_flight_provider_calls"] == pytest.approx(2.88 * 0.5)
    multi = out["multi_agent_derived"]
    assert multi["tokens_per_query"] == pytest.approx(5000.0)
    assert multi["calls_per_query"] == pytest.approx(3.1)
    assert multi["daily_provider_bound_answered"] == pytest.approx(40.0)
    assert "does not implement multi mode" in multi["label"]


def test_without_tpd_the_global_cap_binds():
    inputs = dict(INPUTS, tpd=None)
    out = capacity(inputs)
    assert out["daily_provider_bound_answered"] == 800
