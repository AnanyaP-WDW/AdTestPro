"""Benchmark metric unit tests (hand-calculated; stdlib only)."""

import math

from benchmarks.evaluate import (
    f1_pairwise,
    mae,
    mean_bias,
    pairwise_accuracy,
    per_ad_stability,
    replay_cached,
    scoring_gates,
    spearman,
    variance_ratio,
)


def test_spearman_known_values():
    assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert abs(spearman([1, 2, 3], [2, 1, 3]) - 0.5) < 1e-9
    assert spearman([1], [1]) == 0.0  # degenerate


def test_mae_bias_variance():
    assert mae([1, 2, 3], [1, 2, 4]) == 1 / 3
    assert mean_bias([2, 4], [1, 3]) == 1.0
    assert abs(variance_ratio([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-9


def test_f1_and_pairwise():
    assert f1_pairwise(["a", "b"], ["a", "b"]) == 1.0
    assert f1_pairwise(["a"], ["b"]) == 0.0
    assert f1_pairwise([], []) == 1.0
    pred = {"a": 4.0, "b": 2.0}
    human = {"a": 5.0, "b": 1.0}
    assert pairwise_accuracy(pred, human, [("a", "b")]) == 1.0
    assert pairwise_accuracy(pred, human, [("b", "a")]) == 1.0


def test_stability_and_gates():
    runs = [{"q1": 4.0}, {"q1": 4.1}, {"q1": 3.9}]
    stab = per_ad_stability(runs)
    assert stab["q1"] <= 0.20
    pred = {f"ad{i}": {"clarity": float(i)} for i in range(1, 7)}
    human = {f"ad{i}": {"clarity": float(i)} for i in range(1, 7)}
    gates = scoring_gates(pred, human)
    assert all(g["pass"] for g in gates)


def test_replay_cached_bit_identical():
    report = replay_cached()
    assert report["pass"] is True


def test_v2_persona_order_invariance():
    """V2: order randomization moves aggregates by 0.0 (<= 0.15 gate)."""
    import random

    from app.core.pipeline import aggregate
    from app.core.models import PersonaResponse

    base = [PersonaResponse(
        persona_id=f"p{i:02d}",
        answers=[{"question_id": "clarity", "rating": (i % 5) + 1,
                  "explanation": "e", "evidence_ids": ["o1"], "confidence": 50}])
        for i in range(12)]
    ref = aggregate(base, ["clarity"]).overall_mean
    random.seed(7)
    shuffled = list(base)
    random.shuffle(shuffled)
    assert aggregate(shuffled, ["clarity"]).overall_mean == ref
