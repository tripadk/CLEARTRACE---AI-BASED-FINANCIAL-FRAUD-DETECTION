from datetime import datetime, timedelta

from app.services.detection import DetectionConfig, detect
from app.services.demo import demo_transactions


def test_demo_data_exercises_graph_and_temporal_signals():
    results = detect(demo_transactions(seed=7, count=24))
    assert len(results) == 33
    assert any(x["graph_score"] > 0 for x in results)
    assert any(x["temporal_score"] > 0 for x in results)
    assert all(0 <= x["risk_score"] <= 100 for x in results)


def test_small_sample_has_stable_zero_anomaly_signal():
    now = datetime(2026, 1, 1)
    rows = [{"transaction_id": f"t{i}", "timestamp": (now + timedelta(minutes=i)).isoformat(),
             "sender": "a", "receiver": f"b{i}", "amount": 100 + i} for i in range(3)]
    out = detect(rows)
    assert len(out) == 3
    assert all(x["anomaly_score"] == 0 for x in out)


def test_detection_never_assigns_confirmed_labels():
    rows = detect(demo_transactions(count=2))
    assert all("label" not in x for x in rows)
    assert all(x["reasons"] for x in rows)


def test_bounded_directed_cycle_has_explainable_transaction_evidence():
    now = datetime(2026, 1, 1)
    rows = [{"transaction_id": f"cycle-{i}", "timestamp": (now + timedelta(minutes=i)).isoformat(),
             "sender": a, "receiver": b, "amount": 5000} for i, (a, b) in enumerate([("A", "B"), ("B", "C"), ("C", "A")])]
    result = detect(rows)
    alert = result[-1]
    assert "circular_transfer" in alert["contributing_signals"]
    assert set(alert["supporting_transaction_ids"]) == {"cycle-0", "cycle-1", "cycle-2"}
    assert set(alert["related_accounts"]) == {"A", "B", "C"}


def test_rapid_movement_and_structuring_like_sequence_use_prior_rows():
    now = datetime(2026, 1, 1)
    rapid = [{"transaction_id": f"r{i}", "timestamp": (now + timedelta(minutes=i * 4)).isoformat(),
              "sender": "A", "receiver": f"B{i}", "amount": 2500} for i in range(3)]
    rapid_result = detect(rapid)
    assert "rapid_transfers" in rapid_result[-1]["contributing_signals"]
    assert "r2" not in rapid_result[0]["supporting_transaction_ids"]
    small = [{"transaction_id": f"s{i}", "timestamp": (now + timedelta(hours=i)).isoformat(),
              "sender": "X", "receiver": f"Y{i}", "amount": 800} for i in range(5)]
    small_result = detect(small, {"structuring_min_transfers": 5, "structuring_window_hours": 24})
    assert "repeated_small_transfers" in small_result[-1]["contributing_signals"]
    assert not any("repeated_small_transfers" in x["contributing_signals"] for x in small_result[:-1])


def test_normal_transactions_have_low_risk_and_configurable_weights():
    now = datetime(2026, 1, 1)
    rows = [{"transaction_id": f"n{i}", "timestamp": (now + timedelta(days=i)).isoformat(),
             "sender": f"A{i}", "receiver": f"B{i}", "amount": 250} for i in range(12)]
    normal = detect(rows)
    assert max(x["risk_score"] for x in normal) < 40
    zero_weights = detect(rows, DetectionConfig(graph_weight=0, temporal_weight=0, anomaly_weight=0, rule_weight=1))
    assert max(x["risk_score"] for x in zero_weights) == 0


def test_walk_forward_evaluation_excludes_training_period_from_metrics():
    now = datetime(2026, 1, 1)
    rows = [{"transaction_id": f"w{i}", "timestamp": (now + timedelta(hours=i)).isoformat(),
             "sender": f"A{i%3}", "receiver": f"B{i%5}", "amount": 100 + i,
             "source_label": str(i % 2), "label_source": "dataset"} for i in range(20)]
    result = detect(rows)
    assert all(not x["evaluation_eligible"] for x in result[:14])
    assert all(x["evaluation_eligible"] for x in result[14:])


def test_structuring_amounts_are_not_combined_across_currencies_or_unknown_units():
    now = datetime(2026, 1, 1)
    rows = [{"transaction_id": f"c{i}", "timestamp": (now + timedelta(hours=i)).isoformat(),
             "sender": "A", "receiver": f"B{i}", "amount": 800,
             "currency": "USD" if i == 0 else "EUR"} for i in range(5)]
    result = detect(rows)
    assert all("repeated_small_transfers" not in x["contributing_signals"] for x in result)


def test_simulation_steps_keep_ties_and_use_step_windows_without_dates():
    rows = [{"transaction_id": f"s{i}", "timestamp": None, "simulation_step": step,
             "sender": "A", "receiver": f"B{i}", "amount": 100}
            for i, step in enumerate([0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9])]
    result = detect(rows, {"rapid_window_steps": 1, "rapid_min_transfers": 3,
                           "structuring_window_steps": 4, "structuring_min_transfers": 5})
    assert [x["simulation_step"] for x in result] == [x["simulation_step"] for x in rows]
    assert all(x["timestamp"] is None for x in result)
    assert "repeated_small_transfers" in result[8]["contributing_signals"]
    eligible_steps = {x["simulation_step"] for x in result if x["evaluation_eligible"]}
    validation_steps = {x["simulation_step"] for x in result if x["validation_eligible"]}
    training_steps = {x["simulation_step"] for x in result if not x["evaluation_eligible"] and not x["validation_eligible"]}
    assert not eligible_steps.intersection(training_steps)
    assert not eligible_steps.intersection(validation_steps)
    assert not validation_steps.intersection(training_steps)
    one_tied_step = [dict(row, transaction_id=f"tied-{i}", simulation_step=2) for i, row in enumerate(rows[:10])]
    assert not any(x["evaluation_eligible"] or x["validation_eligible"] for x in detect(one_tied_step))


def test_same_step_cycle_and_fan_in_are_graph_evidence_with_support():
    cycle = [{"transaction_id": f"g{i}", "timestamp": None, "simulation_step": 0,
              "sender": a, "receiver": b, "amount": 10, "source_dataset": "fixture", "currency_missing": True}
             for i, (a, b) in enumerate([("A", "B"), ("B", "C"), ("C", "A")])]
    detected = detect(cycle)
    assert all("circular_transfer" in row["contributing_signals"] for row in detected)
    assert all(set(row["supporting_transaction_ids"]) == {"g0", "g1", "g2"} for row in detected)
    reordered = detect(list(reversed(cycle)))
    assert {x["transaction_id"]: x["risk_score"] for x in detected} == {x["transaction_id"]: x["risk_score"] for x in reordered}

    fan_in = [{"transaction_id": f"f{i}", "timestamp": None, "simulation_step": 0,
               "sender": f"S{i}", "receiver": "R", "amount": 1, "source_dataset": "fixture", "currency_missing": True}
              for i in range(5)]
    detected = detect(fan_in, {"fan_in_min_accounts": 5})
    assert all("fan_in_relationship" in row["contributing_signals"] for row in detected)
    assert all(set(row["supporting_transaction_ids"]) == {f"f{i}" for i in range(5)} for row in detected)
