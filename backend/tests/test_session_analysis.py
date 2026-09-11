"""Unit tests for the deterministic parts of post-session analysis.

The LLM synthesis (narrative/takeaways/strengths) is not exercised here -- only
the pure-Python rollup and the no-network short-circuit, which is where the
correctness-sensitive logic lives.
"""

from datetime import datetime, timedelta

import pytest

import session_analysis
from session_analysis import (
    aggregate_session,
    analyze_session,
    _is_transient_error,
    _format_per_turn,
)


def _turn(n, pei, psq, ccm, tsi, clm, ras, summary=""):
    return {
        "turn": n,
        "pei": pei,
        "scores": {"PSQ": psq, "CCM": ccm, "TSI": tsi, "CLM": clm, "RAS": ras},
        "classification": "Intermediate",
        "turn_summary": summary,
    }


def test_aggregate_empty_is_safe():
    out = aggregate_session([])
    assert out["turns_analyzed"] == 0
    assert out["session_pei"] is None
    assert out["level"] is None
    assert out["trend"] is None
    assert out["strongest_dimension"] is None


def test_aggregate_averages_and_extremes():
    per_turn = [
        _turn(1, 55, 60, 50, 40, 70, 55),
        _turn(2, 72, 80, 70, 65, 75, 68),
    ]
    out = aggregate_session(per_turn)
    assert out["turns_analyzed"] == 2
    assert out["session_pei"] == 63.5
    assert out["level"] == "Intermediate"
    assert out["dimension_averages"]["PSQ"] == 70.0
    assert out["dimension_averages"]["TSI"] == 52.5
    # CLM (72.5) is highest, TSI (52.5) is lowest of the averages.
    assert out["strongest_dimension"] == "CLM"
    assert out["weakest_dimension"] == "TSI"
    assert out["pei_series"] == [55.0, 72.0]   # per-turn trajectory for the sparkline


def test_level_bands_match_evaluator():
    assert aggregate_session([_turn(1, 30, 30, 30, 30, 30, 30)])["level"] == "Novice"
    assert aggregate_session([_turn(1, 55, 55, 55, 55, 55, 55)])["level"] == "Intermediate"
    assert aggregate_session([_turn(1, 85, 85, 85, 85, 85, 85)])["level"] == "Advanced"


def test_trend_direction_improving():
    per_turn = [_turn(1, 40, 40, 40, 40, 40, 40), _turn(2, 70, 70, 70, 70, 70, 70)]
    trend = aggregate_session(per_turn)["trend"]
    assert trend["direction"] == "improving"
    assert trend["delta"] == 30.0


def test_trend_steady_within_threshold():
    per_turn = [_turn(1, 60, 60, 60, 60, 60, 60), _turn(2, 62, 62, 62, 62, 62, 62)]
    assert aggregate_session(per_turn)["trend"]["direction"] == "steady"


def test_trend_needs_two_turns():
    assert aggregate_session([_turn(1, 60, 60, 60, 60, 60, 60)])["trend"] is None


def test_unscored_turns_ignored():
    per_turn = [
        _turn(1, 60, 60, 60, 60, 60, 60),
        {"turn": 2, "pei": None, "scores": {}, "classification": None, "turn_summary": ""},
    ]
    out = aggregate_session(per_turn)
    assert out["turns_analyzed"] == 1


@pytest.mark.asyncio
async def test_analyze_session_short_circuits_without_scored_turns():
    # No scored turns -> must NOT call the LLM; returns a ready, empty rollup.
    out = await analyze_session(transcript=[], per_turn=[], challenge=None)
    assert out["status"] == "ready"
    assert out["turns_analyzed"] == 0
    assert out["takeaways"] == []
    assert "narrative" in out


# --- #1 retry behavior --------------------------------------------------------

def test_per_turn_format_surfaces_suggestions_and_red_flags():
    # #1: the concrete per-turn feedback must reach the prompt so the analyst
    # consolidates it instead of inventing generic advice.
    per_turn = [{
        "turn": 1, "pei": 55, "classification": "Intermediate",
        "turn_summary": "decent start",
        "suggestions": ["specify the tie-breaking rule"],
        "red_flags": ["asked AI to decide scope for you"],
    }]
    out = _format_per_turn(per_turn)
    assert "specify the tie-breaking rule" in out
    assert "asked AI to decide scope for you" in out
    assert "suggestion:" in out and "red flag:" in out


def test_transient_error_classification():
    assert _is_transient_error(RuntimeError("HTTP 429 rate limit"))
    assert _is_transient_error(RuntimeError("connection timed out"))
    assert _is_transient_error(RuntimeError("503 service unavailable"))
    assert not _is_transient_error(ValueError("invalid schema field"))


class _FakeOut:
    narrative = "You stayed in control across the session."
    takeaways = ["a", "b", "c", "d"]   # >3 on purpose: must be truncated
    strengths = ["x", "y", "z"]         # >2 on purpose: must be truncated


class _FakeResult:
    final_output = _FakeOut()


@pytest.fixture
def _no_sleep(monkeypatch):
    async def _instant(_):
        return None
    monkeypatch.setattr(session_analysis.asyncio, "sleep", _instant)


_ONE_TURN = [_turn(1, 60, 60, 60, 60, 60, 60, "did ok")]


@pytest.mark.asyncio
async def test_retries_transient_then_succeeds(monkeypatch, _no_sleep):
    calls = {"n": 0}

    async def fake_run(agent, input=None, run_config=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 rate limit")
        return _FakeResult()

    monkeypatch.setattr(session_analysis.Runner, "run", fake_run)
    out = await analyze_session(transcript=[], per_turn=_ONE_TURN, challenge=None)
    assert calls["n"] == 3          # failed twice, succeeded on the third
    assert out["status"] == "ready"
    assert out["narrative"].startswith("You stayed")
    assert len(out["takeaways"]) == 3   # truncated
    assert len(out["strengths"]) == 2   # truncated


@pytest.mark.asyncio
async def test_raises_after_exhausting_retries(monkeypatch, _no_sleep):
    async def fake_run(agent, input=None, run_config=None):
        raise RuntimeError("503 unavailable")

    monkeypatch.setattr(session_analysis.Runner, "run", fake_run)
    with pytest.raises(RuntimeError):
        await analyze_session(transcript=[], per_turn=_ONE_TURN, challenge=None)


# --- #2 stale-pending detection ----------------------------------------------

def test_pending_staleness():
    from main import _pending_is_stale, _pending_blob, _ANALYSIS_STALE_SECONDS

    fresh = _pending_blob()
    assert _pending_is_stale(fresh) is False          # just created

    old_iso = (datetime.utcnow() - timedelta(seconds=_ANALYSIS_STALE_SECONDS + 60)).isoformat()
    assert _pending_is_stale({"status": "pending", "pending_at": old_iso}) is True

    assert _pending_is_stale({"status": "pending"}) is True   # legacy: no timestamp
    assert _pending_is_stale(None) is True
