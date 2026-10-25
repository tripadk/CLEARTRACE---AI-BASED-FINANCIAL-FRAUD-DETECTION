import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.db.database import get_db
from app.models.transaction import Transaction
from app.services.detection import DetectionConfig, detect
from app.services.demo import demo_transactions
from app.services.dataset_import import import_csv, inspect_csv, parse_binary_label

router = APIRouter(prefix="/api")


def as_dict(tx: Transaction):
    timestamp = None if tx.simulation_step is not None else (tx.timestamp.isoformat() if hasattr(tx.timestamp, "isoformat") else str(tx.timestamp))
    return {"id": tx.id, "transaction_id": tx.transaction_id, "timestamp": timestamp,
            "simulation_step": tx.simulation_step, "source_timestamp_value": tx.source_timestamp_value,
            "source_alert_id": tx.source_alert_id,
            "sender": tx.sender, "receiver": tx.receiver, "amount": tx.amount, "currency": tx.currency,
            "currency_missing": bool(tx.currency_missing), "import_id": tx.import_id,
            "channel": tx.channel, "description": tx.description, "rule_score": tx.rule_score,
            "graph_score": tx.graph_score, "temporal_score": tx.temporal_score, "anomaly_score": tx.anomaly_score,
            "risk_score": tx.risk_score, "reasons": json.loads(tx.reasons or "[]"), "review_status": tx.review_status,
            "source_transaction_id": tx.source_transaction_id, "source_label": tx.source_label,
            "label_source": tx.label_source or "none", "source_dataset": tx.source_dataset or "local",
            "source_row": tx.source_row, "related_accounts": json.loads(tx.related_accounts or "[]"),
            "supporting_transaction_ids": json.loads(tx.supporting_transaction_ids or "[]"),
            "contributing_signals": json.loads(tx.contributing_signals or "[]"),
            "evaluation_eligible": bool(tx.evaluation_eligible), "validation_eligible": bool(tx.validation_eligible),
            "alert_threshold": tx.alert_threshold or 40}


def _save(db: Session, rows: list[dict], replace: bool = False, config: dict | None = None):
    if replace:
        db.query(Transaction).delete()
        db.flush()
    existing = set(db.scalars(select(Transaction.transaction_id)).all())
    fresh = [r for r in rows if r["transaction_id"] not in existing]
    if not fresh:
        db.commit()
        return 0
    scored = detect(fresh, config)
    for row in scored:
        value = row.get("timestamp")
        timestamp = "SIMULATION_STEP" if row.get("simulation_step") is not None else (value.isoformat() if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat())
        tx = Transaction(transaction_id=row["transaction_id"], timestamp=timestamp, simulation_step=row.get("simulation_step"),
                           source_timestamp_value=row.get("source_timestamp_value"), source_alert_id=row.get("source_alert_id"), sender=row["sender"],
                           receiver=row["receiver"], amount=float(row["amount"]), currency=row.get("currency", "USD"),
                           currency_missing=bool(row.get("currency_missing", False)), import_id=row.get("import_id"),
                           channel=row.get("channel", "wire"), description=row.get("description", ""),
                           rule_score=row["rule_score"], graph_score=row["graph_score"], temporal_score=row["temporal_score"],
                           anomaly_score=row["anomaly_score"], risk_score=row["risk_score"], reasons=json.dumps(row["reasons"]),
                           source_transaction_id=row.get("source_transaction_id"), source_label=row.get("source_label"),
                           label_source=row.get("label_source", "none"), source_dataset=row.get("source_dataset", "local"),
                           source_row=row.get("source_row"), source_record=json.dumps(row.get("source_record", {}), ensure_ascii=False),
                           related_accounts=json.dumps(row.get("related_accounts", [])),
                           supporting_transaction_ids=json.dumps(row.get("supporting_transaction_ids", [])),
                           contributing_signals=json.dumps(row.get("contributing_signals", [])),
                           evaluation_eligible=bool(row.get("evaluation_eligible", False)),
                           alert_threshold=int(row.get("alert_threshold", 40)))
        db.add(tx)
    db.commit()
    return len(scored)


def _analyze_import(db: Session, incoming: list[dict], config: dict, scope: str, dataset_name: str):
    """Insert deduplicated rows, then rescore the requested imported population together."""
    if scope not in {"import", "all_imported"}:
        raise ValueError("analysis_scope must be 'import' or 'all_imported'.")
    existing_by_id = {tx.transaction_id: tx for tx in db.scalars(select(Transaction)).all()}
    fresh = [dict(row) for row in incoming if row["transaction_id"] not in existing_by_id]
    import_id = str(uuid.uuid4())
    for row in fresh:
        row["import_id"] = import_id
    selected = [tx for tx in existing_by_id.values()
                if scope == "all_imported" and
                (tx.import_id is not None or (tx.source_dataset or "local") != "local")]
    if scope == "all_imported" and selected and incoming:
        selected_kinds = {tx.simulation_step is not None for tx in selected}
        incoming_kinds = {row.get("simulation_step") is not None for row in incoming}
        if len(selected_kinds | incoming_kinds) > 1:
            raise ValueError("Calendar timestamps and simulation steps cannot be analyzed together; choose a compatible import scope.")
    combined = []
    target_ids = set()
    for tx in selected:
        target_ids.add(tx.transaction_id)
        combined.append({"transaction_id": tx.transaction_id, "timestamp": None if tx.simulation_step is not None else str(tx.timestamp), "simulation_step": tx.simulation_step,
                         "sender": tx.sender, "receiver": tx.receiver, "amount": tx.amount,
                         "currency": tx.currency, "currency_missing": tx.currency_missing,
                         "source_dataset": tx.source_dataset})
    combined.extend(fresh)
    target_ids.update(row["transaction_id"] for row in fresh)
    scored = detect(combined, config)
    for row in scored:
        tx = existing_by_id.get(row["transaction_id"])
        if tx is None:
            value = row.get("timestamp")
            timestamp = "SIMULATION_STEP" if row.get("simulation_step") is not None else (value.isoformat() if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat())
            tx = Transaction(transaction_id=row["transaction_id"], timestamp=timestamp, simulation_step=row.get("simulation_step"),
                source_timestamp_value=row.get("source_timestamp_value"), source_alert_id=row.get("source_alert_id"), sender=row["sender"],
                receiver=row["receiver"], amount=float(row["amount"]), currency=row.get("currency") or "USD",
                currency_missing=bool(row.get("currency_missing", False)), import_id=row.get("import_id"),
                channel=row.get("channel", "wire"), description=row.get("description", ""),
                source_transaction_id=row.get("source_transaction_id"), source_label=row.get("source_label"),
                label_source=row.get("label_source", "none"), source_dataset=row.get("source_dataset", "local"),
                source_row=row.get("source_row"), source_record=json.dumps(row.get("source_record", {}), ensure_ascii=False))
            db.add(tx)
        tx.rule_score=row["rule_score"]; tx.graph_score=row["graph_score"]
        tx.temporal_score=row["temporal_score"]; tx.anomaly_score=row["anomaly_score"]
        tx.risk_score=row["risk_score"]; tx.reasons=json.dumps(row["reasons"])
        tx.related_accounts=json.dumps(row["related_accounts"])
        tx.supporting_transaction_ids=json.dumps(row["supporting_transaction_ids"])
        tx.contributing_signals=json.dumps(row["contributing_signals"])
        tx.evaluation_eligible=bool(row["evaluation_eligible"]); tx.validation_eligible=bool(row.get("validation_eligible", False))
        tx.alert_threshold=int(row["alert_threshold"])
    db.commit()
    return len(fresh), import_id


@router.get("/health")
def health():
    return {"status": "ok", "application": "ClearTrace AML"}


@router.post("/demo/load")
def load_demo(db: Session = Depends(get_db)):
    try:
        count = _save(db, demo_transactions())
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Could not load demonstration data: {exc}") from exc
    return {"inserted": count, "message": f"Loaded {count} synthetic transactions. Alerts are risk indicators, not findings of wrongdoing."}


@router.get("/transactions")
def list_transactions(q: str = "", severity: str = "all", status: str = "all", limit: int = Query(100, ge=1, le=500),
                     offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = select(Transaction)
    if q:
        needle = f"%{q}%"
        stmt = stmt.where(or_(Transaction.transaction_id.ilike(needle), Transaction.sender.ilike(needle),
                              Transaction.source_transaction_id.ilike(needle),
                              Transaction.receiver.ilike(needle), Transaction.description.ilike(needle)))
    if severity == "high": stmt = stmt.where(Transaction.risk_score >= func.max(70, Transaction.alert_threshold))
    if severity == "medium": stmt = stmt.where(Transaction.risk_score >= Transaction.alert_threshold, Transaction.risk_score < func.max(70, Transaction.alert_threshold))
    elif severity == "low": stmt = stmt.where(Transaction.risk_score < Transaction.alert_threshold)
    if status != "all": stmt = stmt.where(Transaction.review_status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    records = db.scalars(stmt.order_by(Transaction.simulation_step.desc().nulls_last(),
                                       Transaction.timestamp.desc().nulls_last()).offset(offset).limit(limit)).all()
    return {"items": [as_dict(x) for x in records], "total": total}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    items = db.scalars(select(Transaction).order_by(Transaction.simulation_step.asc().nulls_first(),
                               Transaction.timestamp.asc().nulls_last())).all()
    data = [as_dict(x) for x in items]
    accounts = set()
    for x in data: accounts.update((x["sender"], x["receiver"]))
    alert_rows = [x for x in data if x["risk_score"] >= x["alert_threshold"]]
    day_map = {}
    currencies = {x["currency"].upper() for x in data if x["currency"] and not x["currency_missing"]}
    has_unknown_currency = any(x["currency_missing"] or not x["currency"] for x in data)
    for x in data:
        step = x.get("simulation_step")
        day = f"step:{step}" if step is not None else str(x["timestamp"])[:10]
        item = day_map.setdefault(day, {"date": None if step is not None else day,
                                        "simulation_step": step, "volume": 0, "count": 0, "flagged": 0})
        if not x["currency_missing"] and x["currency"]:
            item["volume_by_currency"] = item.get("volume_by_currency", {})
            item["volume_by_currency"][x["currency"].upper()] = item["volume_by_currency"].get(x["currency"].upper(), 0) + x["amount"]
        item["count"] += 1
        item["flagged"] += int(x["risk_score"] >= x["alert_threshold"])
    comparable = len(currencies) == 1 and not has_unknown_currency
    only_currency = next(iter(currencies)) if len(currencies) == 1 else None
    for item in day_map.values():
        item["volume"] = round(item.get("volume_by_currency", {}).get(only_currency, 0), 2) if comparable else None
    currency_totals = {}
    for x in data:
        if not x["currency_missing"] and x["currency"]:
            c=x["currency"].upper(); currency_totals[c]=currency_totals.get(c, 0)+x["amount"]
    activity = sorted(day_map.values(), key=lambda x: (x["simulation_step"] is None, x["simulation_step"] if x["simulation_step"] is not None else x["date"]))[-14:]
    return {"transaction_count": len(data), "total_volume": round(sum(x["amount"] for x in data), 2) if comparable else None,
            "total_volume_currency": only_currency if comparable else None, "currency_totals": {k: round(v, 2) for k,v in currency_totals.items()},
            "currency_warning": ("Currency metadata is missing or inconsistent; monetary totals are shown separately and are not combined." if not comparable and data else None),
            "volume_comparable": comparable,
            "flagged_accounts": len({a for x in alert_rows for a in (x["sender"], x["receiver"])}),
            "alert_count": len(alert_rows), "high_alerts": sum(x["risk_score"] >= max(70, x["alert_threshold"]) for x in data),
            "medium_alerts": sum(x["alert_threshold"] <= x["risk_score"] < max(70, x["alert_threshold"]) for x in data), "accounts_monitored": len(accounts),
            "labelled_count": sum(x["source_label"] is not None for x in data),
            "dataset_count": len({x["source_dataset"] for x in data if x["import_id"] is not None or x["source_dataset"] != "local"}),
            "activity": activity, "recent_alerts": sorted(alert_rows, key=lambda x: x["risk_score"], reverse=True)[:8]}


@router.post("/transactions/upload")
async def upload_csv(file: UploadFile = File(...), mapping: str = Form("{}"), dataset_name: str = Form(""),
                     detection_config: str = Form("{}"), analysis_scope: str = Form("import"),
                     timestamp_kind: str = Form("datetime"), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a .csv file.")
    try:
        selected_mapping = json.loads(mapping)
        config = json.loads(detection_config)
        DetectionConfig(**config)
        result = import_csv(await file.read(), file.filename, selected_mapping, dataset_name or file.filename, timestamp_kind)
        if not result["valid"]:
            return {"inserted": 0, "skipped_duplicates": 0, "invalid_count": len(result["invalid_rows"]),
                    "invalid_rows": result["invalid_rows"], "headers": result["headers"], "mapping": result["mapping"],
                    "labelled_rows": 0, "message": "No valid transaction rows found; correct the reported CSV rows and retry."}
        count, import_id = _analyze_import(db, result["valid"], config, analysis_scope, dataset_name or file.filename)
        duplicates = len(result["valid"]) - count
        return {"inserted": count, "skipped_duplicates": duplicates, "invalid_count": len(result["invalid_rows"]),
                "invalid_rows": result["invalid_rows"], "headers": result["headers"], "mapping": result["mapping"],
                "labelled_rows": result["labelled_rows"], "import_id": import_id, "analysis_scope": analysis_scope,
                "currency_warning": "Currency column is unmapped; monetary values are treated as unknown currency." if not result["mapping"].get("currency") else None,
                "message": f"Imported {count} transactions and analyzed {analysis_scope.replace('_', ' ')} data. Dataset labels remain separate from generated risk alerts."}
    except HTTPException:
        raise
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/transactions/inspect")
async def inspect_transaction_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a .csv file.")
    try:
        return inspect_csv(await file.read())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/evaluation")
def evaluation(labels_verified: bool = False, positive_label: str | None = None, negative_label: str | None = None,
               threshold: int = Query(40, ge=0, le=100), max_validation_fpr: float = Query(.01, ge=0, le=1),
               db: Session = Depends(get_db)):
    if not labels_verified:
        return {"available": False, "reason": "Confirm the imported dataset labels are reference labels before calculating evaluation metrics."}
    labelled = db.scalars(select(Transaction).where(Transaction.label_source == "dataset", Transaction.source_label.is_not(None),
                                                  or_(Transaction.evaluation_eligible.is_(True), Transaction.validation_eligible.is_(True)))).all()
    if not positive_label or not negative_label or positive_label == negative_label:
        return {"available": False, "evaluated_sample_count": 0, "positive_class_count": 0,
                "reason": "Supply distinct positive_label and negative_label values explicitly; labels are never inferred."}
    validation, holdout = [], []
    for tx in labelled:
        label = parse_binary_label(tx.source_label, positive_label, negative_label)
        if label is None:
            continue
        pair = (label, float(tx.risk_score))
        if tx.validation_eligible: validation.append(pair)
        elif tx.evaluation_eligible: holdout.append(pair)

    def metrics(pairs, cutoff):
        actual = [label for label, _ in pairs]
        predicted = [int(score >= cutoff) for _, score in pairs]
        if not actual:
            return {"evaluated_sample_count": 0, "positive_class_count": 0, "negative_class_count": 0}
        tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[0, 1]).ravel()
        positives = sum(actual)
        negatives = len(actual) - positives
        return {"threshold": cutoff, "evaluated_sample_count": len(actual),
                "positive_class_count": positives, "negative_class_count": negatives,
                "positive_class_proportion": positives / len(actual), "negative_class_proportion": negatives / len(actual),
                "precision": precision_score(actual, predicted, zero_division=0),
                "recall": recall_score(actual, predicted, zero_division=0),
                "f1": f1_score(actual, predicted, zero_division=0),
                "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
                "true_positives": int(tp), "false_positives": int(fp),
                "true_negatives": int(tn), "false_negatives": int(fn)}

    val_pos = sum(y for y, _ in validation)
    val_neg = len(validation) - val_pos
    test_pos = sum(y for y, _ in holdout)
    test_neg = len(holdout) - test_pos
    if not holdout or not validation or not val_pos or not val_neg or not test_pos or not test_neg:
        return {"available": False, "validation_sample_count": len(validation), "validation_positive_count": val_pos,
                "evaluated_sample_count": len(holdout), "positive_class_count": test_pos, "negative_class_count": test_neg,
                "reason": "Threshold calibration and evaluation require explicitly mapped positive and negative labels in both the chronological validation and later holdout partitions."}
    # Threshold selection sees validation labels only. Bound false-positive burden;
    # if validation finds no true positives, fail closed instead of choosing all-positive.
    validation_candidates = [(t, metrics(validation, t)) for t in range(0, 102)]
    candidates = [(t, m) for t, m in validation_candidates if m["false_positive_rate"] <= max_validation_fpr]
    best_f1 = max(m["f1"] for _, m in candidates)
    selected, validation_metrics = (max(((t, m) for t, m in candidates if m["f1"] == best_f1),
                                        key=lambda pair: (pair[1]["precision"], pair[0]))
                                    if best_f1 > 0 else (101, metrics(validation, 101)))
    calibrated = metrics(holdout, selected)
    current = metrics(holdout, threshold)
    all_negative = metrics(holdout, 101)
    is_amlsim = any(tx.simulation_step is not None for tx in labelled)
    return {"available": True,
            "evaluation_type": "synthetic AMLSim evaluation; chronological train/validation/70-30 simulation-step holdout grouped by step" if is_amlsim else "chronological train/validation/holdout; explicitly mapped dataset reference labels",
            **calibrated, "fixed_detector_threshold": threshold,
            "validation_sample_count": len(validation), "validation_positive_count": val_pos,
            "validation_negative_count": val_neg, "validation_selected_threshold": selected,
            "validation_selected_f1": validation_metrics["f1"], "max_validation_fpr": max_validation_fpr,
            "threshold_selection": "Maximize validation F1 subject to the configured validation false-positive-rate cap; use all-negative if validation detects no positives.",
            "baselines": {"all_negative": all_negative, "existing_detector": current}}


@router.get("/alerts")
def alerts(status: str = "all", severity: str = "all", db: Session = Depends(get_db)):
    stmt = select(Transaction).where(Transaction.risk_score >= Transaction.alert_threshold)
    if status != "all": stmt = stmt.where(Transaction.review_status == status)
    if severity == "high": stmt = stmt.where(Transaction.risk_score >= func.max(70, Transaction.alert_threshold))
    if severity == "medium": stmt = stmt.where(Transaction.risk_score < func.max(70, Transaction.alert_threshold))
    return [as_dict(x) for x in db.scalars(stmt.order_by(Transaction.risk_score.desc(), Transaction.simulation_step.desc().nulls_last(),
                                                        Transaction.timestamp.desc().nulls_last())).all()]


@router.patch("/alerts/{transaction_id}/status")
def update_status(transaction_id: str, status: str, db: Session = Depends(get_db)):
    if status not in {"open", "reviewing", "closed"}: raise HTTPException(422, "Status must be open, reviewing, or closed.")
    tx = db.scalar(select(Transaction).where(Transaction.transaction_id == transaction_id))
    if not tx: raise HTTPException(404, "Transaction alert was not found.")
    tx.review_status = status
    db.commit()
    return as_dict(tx)


@router.get("/graph")
def account_graph(account: str = "", db: Session = Depends(get_db)):
    rows = db.scalars(select(Transaction)).all()
    graph = {"nodes": {}, "edges": []}
    for tx in rows:
        if account and account.lower() not in tx.sender.lower() and account.lower() not in tx.receiver.lower(): continue
        for node in (tx.sender, tx.receiver): graph["nodes"].setdefault(node, {"id": node, "label": node})
        graph["edges"].append({"id": tx.transaction_id, "source": tx.sender, "target": tx.receiver, "amount": tx.amount,
                               "risk": tx.risk_score, "timestamp": None if tx.simulation_step is not None else as_dict(tx)["timestamp"],
                               "simulation_step": tx.simulation_step, "source_alert_id": tx.source_alert_id, "currency": tx.currency,
                               "currency_missing": tx.currency_missing,
                               "reasons": json.loads(tx.reasons or "[]"), "related_accounts": json.loads(tx.related_accounts or "[]"),
                               "supporting_transaction_ids": json.loads(tx.supporting_transaction_ids or "[]"),
                               "contributing_signals": json.loads(tx.contributing_signals or "[]")})
    return {"nodes": list(graph["nodes"].values()), "edges": graph["edges"]}
