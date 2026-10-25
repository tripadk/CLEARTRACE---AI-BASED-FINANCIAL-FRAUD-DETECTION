"""Walk-forward graph, temporal, rule and unsupervised AML risk indicators."""
from collections import Counter, defaultdict, deque
from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


def _currency(row):
    missing = row.get("currency_missing", False)
    if pd.isna(missing):
        missing = False
    value = row.get("currency")
    if pd.isna(value):
        value = None
    return "" if missing else str(value or "USD").upper()


def _amount_group(row):
    """Keep known currencies separate and isolate unknown units by source dataset."""
    currency = _currency(row)
    return f"currency:{currency}" if currency else f"source-unit:{row.get('source_dataset') or row.get('import_id') or 'unknown'}"


@dataclass(frozen=True)
class DetectionConfig:
    cycle_max_hops: int = 6
    rapid_window_minutes: int = 60
    rapid_min_transfers: int = 3
    structuring_window_hours: int = 24
    structuring_min_transfers: int = 5
    small_transfer_threshold: float = 1000.0
    large_transfer_threshold: float = 10000.0
    burst_window_minutes: int = 60
    rapid_window_steps: int = 1
    structuring_window_steps: int = 24
    burst_window_steps: int = 1
    fan_in_min_accounts: int = 5
    fan_in_window_steps: int = 1
    burst_min_transfers: int = 5
    alert_threshold: int = 40
    graph_weight: float = 0.30
    temporal_weight: float = 0.25
    anomaly_weight: float = 0.20
    rule_weight: float = 0.25

    def __post_init__(self):
        if min(self.cycle_max_hops, self.rapid_window_minutes, self.rapid_min_transfers,
               self.structuring_window_hours, self.structuring_min_transfers,
               self.burst_window_minutes, self.burst_min_transfers, self.rapid_window_steps,
               self.structuring_window_steps, self.burst_window_steps, self.fan_in_min_accounts,
               self.fan_in_window_steps) < 1:
            raise ValueError("Detection windows and minimum counts must be positive.")
        if min(self.small_transfer_threshold, self.large_transfer_threshold) <= 0:
            raise ValueError("Transfer thresholds must be positive.")
        if not 0 <= self.alert_threshold <= 100:
            raise ValueError("Alert threshold must be between 0 and 100.")
        if min(self.graph_weight, self.temporal_weight, self.anomaly_weight, self.rule_weight) < 0:
            raise ValueError("Signal weights cannot be negative.")


def _past_features(rows):
    outgoing, incoming, outgoing_count, incoming_count = defaultdict(float), defaultdict(float), Counter(), Counter()
    group_amount, group_count = defaultdict(float), Counter()
    values, i = [], 0
    while i < len(rows):
        first = rows[i]
        key = first.get("simulation_step") if first.get("simulation_step") is not None else first["timestamp"]
        j = i + 1
        while j < len(rows):
            other = rows[j].get("simulation_step") if rows[j].get("simulation_step") is not None else rows[j]["timestamp"]
            if other != key: break
            j += 1
        group = rows[i:j]
        # Features for tied rows use history strictly before the whole tied slice.
        for row in group:
            sender, receiver, amount = row["sender"], row["receiver"], float(row["amount"])
            amount_group = _amount_group(row)
            sender_key, receiver_key = (sender, amount_group), (receiver, amount_group)
            hour = 0 if row.get("simulation_step") is not None else pd.Timestamp(row["timestamp"]).hour
            group_mean = group_amount[amount_group] / group_count[amount_group] if group_count[amount_group] else amount
            sender_mean = outgoing[sender_key] / outgoing_count[sender_key] if outgoing_count[sender_key] else group_mean
            receiver_mean = incoming[receiver_key] / incoming_count[receiver_key] if incoming_count[receiver_key] else group_mean
            values.append([np.log1p(amount / max(sender_mean, 1e-9)),
                           np.log1p(outgoing_count[sender_key]), np.log1p(incoming_count[receiver_key]),
                           np.log1p(amount / max(receiver_mean, 1e-9)),
                           np.log1p(amount / max(group_mean, 1e-9)),
                           np.sin(hour * np.pi / 12), np.cos(hour * np.pi / 12)])
        for row in group:
            sender, receiver, amount = row["sender"], row["receiver"], float(row["amount"])
            amount_group = _amount_group(row)
            sender_key, receiver_key = (sender, amount_group), (receiver, amount_group)
            outgoing[sender_key] += amount; outgoing_count[sender_key] += 1
            incoming[receiver_key] += amount; incoming_count[receiver_key] += 1
            group_amount[amount_group] += amount; group_count[amount_group] += 1
        i = j
    return np.asarray(values, dtype=float)


def detect(rows: list[dict], config: DetectionConfig | dict | None = None) -> list[dict]:
    """Score in timestamp order; each row's evidence uses that row and past rows only.

    Isolation Forest fits on the training period, scores validation and holdout rows,
    and splits simulation steps as indivisible chronological groups.
    """
    if not rows:
        return []
    cfg = config if isinstance(config, DetectionConfig) else DetectionConfig(**(config or {}))
    df = pd.DataFrame(rows).copy()
    df["_order"] = np.arange(len(df))
    has_step = df.get("simulation_step", pd.Series([None] * len(df))).notna()
    if has_step.any() and not has_step.all():
        raise ValueError("Calendar timestamps and simulation steps cannot be analyzed together.")
    simulation = bool(has_step.all())
    if simulation: df["simulation_step"] = pd.to_numeric(df["simulation_step"], errors="coerce")
    else: df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    for col in ("sender", "receiver"):
        df[col] = df[col].fillna("").astype(str)
    time_col = "simulation_step" if simulation else "timestamp"
    if df[[time_col, "sender", "receiver", "amount"]].isna().any().any() or (df.amount < 0).any() or (df.sender == "").any() or (df.receiver == "").any():
        raise ValueError("Rows require valid timestamps, account identifiers, and non-negative numeric amounts.")
    df = df.sort_values([time_col, "transaction_id", "_order"], kind="stable").reset_index(drop=True)
    ordered = []
    for row in df.to_dict("records"):
        item = dict(row)
        if not simulation: item["timestamp"] = pd.Timestamp(item["timestamp"]).isoformat()
        ordered.append(item)

    features = _past_features(ordered)
    anomaly = np.zeros(len(ordered), dtype=float)
    test_start = max(8, int(len(ordered) * .70))
    test_start = min(test_start, len(ordered))
    train_end = max(8, int(test_start * .80))
    time_values = [x["simulation_step"] if simulation else x["timestamp"] for x in ordered]
    boundaries = [i for i in range(8, len(ordered)) if time_values[i] != time_values[i - 1]]
    if test_start < len(ordered):
        test_start = min(boundaries, key=lambda i: abs(i - test_start)) if boundaries else len(ordered)
    val_boundaries = [i for i in boundaries if i < test_start]
    if val_boundaries:
        train_end = min(val_boundaries, key=lambda i: abs(i - train_end))
    else:
        train_end = test_start
    train_end = min(train_end, test_start)
    eligible = test_start < len(ordered) and train_end >= 8
    if train_end >= 8 and train_end < len(ordered):
        scaler = StandardScaler().fit(features[:train_end])
        model = IsolationForest(n_estimators=120, contamination="auto", random_state=42, n_jobs=1)
        model.fit(scaler.transform(features[:train_end]))
        raw = -model.score_samples(scaler.transform(features[train_end:]))
        calibration = -model.score_samples(scaler.transform(features[:train_end]))
        low, high = np.quantile(calibration, [.50, .99])
        anomaly[train_end:] = np.clip((raw - low) / max(float(high - low), 1e-9), 0, 1)

    graph = nx.DiGraph()
    outgoing_rows, incoming_rows = defaultdict(deque), defaultdict(deque)
    same_step_out, same_step_in = defaultdict(list), defaultdict(list)
    if simulation:
        for candidate in ordered:
            same_step_out[(candidate["sender"], int(candidate["simulation_step"]))].append(candidate)
            same_step_in[(candidate["receiver"], int(candidate["simulation_step"]))].append(candidate)
    time_groups = defaultdict(list)
    for candidate in ordered:
        key = ("step", int(candidate["simulation_step"])) if simulation else ("time", candidate["timestamp"])
        time_groups[key].append(candidate)
    group_edge_ids = {key: {(x["sender"], x["receiver"]): x["transaction_id"] for x in group}
                      for key, group in time_groups.items()}
    outgoing_count, incoming_count = Counter(), Counter()
    latest_edge_transaction = {}
    outgoing_evidence, incoming_evidence = defaultdict(lambda: deque(maxlen=8)), defaultdict(lambda: deque(maxlen=8))
    day_counts = Counter()
    scored = []
    total_weight = cfg.graph_weight + cfg.temporal_weight + cfg.anomaly_weight + cfg.rule_weight
    if total_weight <= 0:
        raise ValueError("At least one risk-score signal weight must be positive.")

    for pos, row in enumerate(ordered):
        time_key = ("step", int(row["simulation_step"])) if simulation else ("time", row["timestamp"])
        if pos == 0 or time_key != (("step", int(ordered[pos - 1]["simulation_step"])) if simulation else ("time", ordered[pos - 1]["timestamp"])):
            # Tied transactions are a single graph slice, independent of CSV row ordering.
            for member in time_groups[time_key]:
                graph.add_edge(member["sender"], member["receiver"])
        timestamp = None if simulation else pd.Timestamp(row["timestamp"])
        moment = int(row["simulation_step"]) if simulation else timestamp
        sender, receiver, amount = row["sender"], row["receiver"], float(row["amount"])
        currency = _currency(row)
        reasons, signals, related, support = [], [], set(), set()
        temporal_score = 0.0

        # Graph contains current and historical edges only; find a bounded return path.
        graph.add_edge(sender, receiver)
        graph_score = 0.0
        try:
            queue = deque([(receiver, [receiver])]); path = None; visited = {receiver}; examined = 0
            while queue:
                node, route = queue.popleft()
                examined += 1
                if examined > 1000: break
                if len(route) >= cfg.cycle_max_hops: continue
                for nxt in graph.successors(node):
                    if nxt == sender: path = route + [nxt]; queue.clear(); break
                    if nxt not in visited and nxt not in route:
                        visited.add(nxt); queue.append((nxt, route + [nxt]))
            if path and 2 <= len(path) <= cfg.cycle_max_hops:
                graph_score = .95
                related.update(path)
                reasons.append(f"Bounded circular transfer path ({len(path)} accounts)")
                signals.append("circular_transfer")
                for a, b in zip(path, path[1:]):
                    if (a, b) in latest_edge_transaction:
                        support.add(latest_edge_transaction[(a, b)])
                    if (a, b) in group_edge_ids[time_key]:
                        support.add(group_edge_ids[time_key][(a, b)])
                support.add(row["transaction_id"])
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass
        graph.add_edge(sender, receiver, tx_id=row["transaction_id"])

        # Bounded per-account windows avoid scanning the full dataset for every row.
        horizon = max(cfg.structuring_window_steps, cfg.rapid_window_steps, cfg.burst_window_steps) if simulation else max(cfg.structuring_window_hours * 3600, cfg.rapid_window_minutes * 60, cfg.burst_window_minutes * 60)
        elapsed = lambda x: (moment - int(x["simulation_step"])) if simulation else (moment - pd.Timestamp(x["timestamp"])).total_seconds()
        recent_out = outgoing_rows[sender]
        while recent_out and elapsed(recent_out[0]) > horizon:
            recent_out.popleft()
        recent_in = incoming_rows[sender]
        while recent_in and elapsed(recent_in[0]) > horizon:
            recent_in.popleft()
        # Equal simulation steps are tied, so include all tied peers as simultaneous evidence
        # rather than letting CSV row order decide which transfer appears to come first.
        temporal_out = [x for x in recent_out if not simulation or x["simulation_step"] < row["simulation_step"]]
        temporal_in = [x for x in recent_in if not simulation or x["simulation_step"] < row["simulation_step"]]
        if simulation:
            temporal_out += [x for x in same_step_out[(sender, int(row["simulation_step"]))]
                             if x["transaction_id"] != row["transaction_id"]]
            temporal_in += [x for x in same_step_in[(sender, int(row["simulation_step"]))]
                            if x["transaction_id"] != row["transaction_id"]]
        if currency == "USD" and amount >= cfg.large_transfer_threshold:
            reasons.append(f"Large USD transfer (>= {cfg.large_transfer_threshold:,.0f})")
            signals.append("large_transfer")
            rule_score = .55
        else:
            rule_score = 0.0

        small_prior = [x for x in temporal_out if currency and _currency(x) == currency
                       and float(x["amount"]) < cfg.small_transfer_threshold and
                       0 <= elapsed(x) <= (cfg.structuring_window_steps if simulation else cfg.structuring_window_hours * 3600)]
        if currency == "USD" and amount < cfg.small_transfer_threshold and amount >= 0:
            if len(small_prior) + 1 >= cfg.structuring_min_transfers:
                temporal_score = .82
                window_label = f"{cfg.structuring_window_steps} simulation steps" if simulation else f"{cfg.structuring_window_hours}h"
                reasons.append(f"Structuring-like repeated small transfers ({len(small_prior)+1} within {window_label})")
                signals.append("repeated_small_transfers")
                support.update(x["transaction_id"] for x in small_prior)
        else:
            temporal_score = 0.0

        rapid_prior = [x for x in temporal_out if
                       0 <= elapsed(x) <= (cfg.rapid_window_steps if simulation else cfg.rapid_window_minutes * 60)]
        if len(rapid_prior) + 1 >= cfg.rapid_min_transfers:
            temporal_score = max(temporal_score, .76)
            window_label = f"{cfg.rapid_window_steps} simulation steps" if simulation else f"{cfg.rapid_window_minutes} minutes"
            reasons.append(f"Rapid repeated transfers ({len(rapid_prior)+1} within {window_label})")
            signals.append("rapid_transfers")
            support.update(x["transaction_id"] for x in rapid_prior)

        # Multi-hop pass-through: sender received funds recently from a different account.
        pass_through = [x for x in temporal_in if x["sender"] != receiver and
                        0 <= elapsed(x) <= (cfg.rapid_window_steps if simulation else cfg.rapid_window_minutes * 60)]
        if pass_through:
            temporal_score = max(temporal_score, .72)
            reasons.append("Rapid movement follows a recent incoming transfer")
            signals.append("rapid_funds_movement")
            support.update(x["transaction_id"] for x in pass_through[-5:])
            related.update(x["sender"] for x in pass_through[-5:])

        burst_prior = [x for x in temporal_out if
                       0 <= elapsed(x) <= (cfg.burst_window_steps if simulation else cfg.burst_window_minutes * 60)]
        if len(burst_prior) + 1 >= cfg.burst_min_transfers:
            temporal_score = max(temporal_score, .68)
            window_label = f"{cfg.burst_window_steps} simulation steps" if simulation else f"{cfg.burst_window_minutes} minutes"
            reasons.append(f"Unusual transfer burst ({len(burst_prior)+1} in {window_label})")
            signals.append("transfer_burst")
            support.update(x["transaction_id"] for x in burst_prior)
        day_key = (sender, int(moment) if simulation else timestamp.date())
        same_period_count = len(same_step_out[(sender, int(moment))]) if simulation else day_counts[day_key] + 1
        if same_period_count >= cfg.burst_min_transfers:
            temporal_score = max(temporal_score, .62)
            reasons.append("Unusual same-step account activity" if simulation else "Unusual same-day account activity")
            signals.append("same_step_activity" if simulation else "same_day_activity")
        day_counts[day_key] += 1

        fan_in_rows = list(incoming_rows[receiver])
        if simulation:
            fan_in_rows.extend(same_step_in[(receiver, int(row["simulation_step"]))])
            fan_in_rows = [x for x in fan_in_rows if x["transaction_id"] != row["transaction_id"] and
                           (x.get("simulation_step", -1) >= row["simulation_step"] - cfg.fan_in_window_steps)]
        else:
            fan_in_rows = [x for x in fan_in_rows if (timestamp - pd.Timestamp(x["timestamp"])).total_seconds() <= cfg.burst_window_minutes * 60]
        fan_senders = {x["sender"] for x in fan_in_rows} | {sender}
        if len(fan_senders) >= cfg.fan_in_min_accounts:
            graph_score = max(graph_score, .75)
            reasons.append(f"Fan-in to destination from {len(fan_senders)} accounts in the configured window")
            signals.append("fan_in_relationship")
            related.update(fan_senders | {receiver})
            support.update(x["transaction_id"] for x in fan_in_rows)
            support.add(row["transaction_id"])

        if sender == receiver:
            rule_score = min(1.0, rule_score + .3)
            reasons.append("Self-transfer")
            signals.append("self_transfer")
        # Unusually high transaction count based on accounts seen in prior history.
        sender_count = outgoing_count[sender]
        receiver_count = incoming_count[receiver]
        if sender_count >= 8 and receiver_count >= 8:
            graph_score = max(graph_score, .45)
            reasons.append("Previously high-activity sender and receiver accounts")
            signals.append("high_activity_relationship")
            support.update(x["transaction_id"] for x in outgoing_evidence[sender])
            support.update(x["transaction_id"] for x in incoming_evidence[receiver])
            related.update(x["receiver"] for x in outgoing_evidence[sender])
            related.update(x["sender"] for x in incoming_evidence[receiver])
        if graph_score:
            related.update((sender, receiver))
        if rule_score:
            signals.append("rule_threshold")

        # Score using documented weights normalized for configurable weight sets.
        weighted = (cfg.rule_weight * rule_score + cfg.graph_weight * graph_score +
                    cfg.temporal_weight * temporal_score + cfg.anomaly_weight * float(anomaly[pos])) / total_weight
        risk_score = round(100 * weighted)
        if anomaly[pos] >= .65:
            reasons.append("Isolation Forest anomaly relative to earlier transaction history")
            signals.append("isolation_forest")
        if risk_score >= cfg.alert_threshold:
            support.add(row["transaction_id"])
            related.update((sender, receiver))
            signals.append("alert_threshold")
            reasons.append(f"Composite score met configured alert threshold ({cfg.alert_threshold})")
        item_result = {k: v for k, v in row.items() if k != "_order"}
        item_result.update(rule_score=round(rule_score, 3), graph_score=round(graph_score, 3),
                           temporal_score=round(temporal_score, 3), anomaly_score=round(float(anomaly[pos]), 3),
                           risk_score=risk_score, alert_threshold=cfg.alert_threshold,
                           reasons=reasons or ["No elevated signal identified"],
                           contributing_signals=sorted(set(signals)), related_accounts=sorted(related),
                           supporting_transaction_ids=sorted(support),
                           validation_eligible=bool(train_end <= pos < test_start and train_end < test_start),
                           evaluation_eligible=bool(eligible and pos >= test_start))
        scored.append(item_result)
        outgoing_rows[sender].append(row)
        incoming_rows[receiver].append(row)
        outgoing_count[sender] += 1
        incoming_count[receiver] += 1
        outgoing_evidence[sender].append(row)
        incoming_evidence[receiver].append(row)
        latest_edge_transaction[(sender, receiver)] = row["transaction_id"]

    # Return results in caller order, preserving stable API import semantics.
    original_order = {r["transaction_id"]: i for i, r in enumerate(rows)}
    scored.sort(key=lambda x: original_order[x["transaction_id"]])
    return scored
