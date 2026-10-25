"""CSV inspection, IBM AMLSim header inference and row-level validation."""
import csv
import hashlib
import io
import re
from datetime import datetime

from app.schemas.transaction import TransactionIn


ALIASES = {
    "transaction_id": ("transaction_id", "tx_id", "transactionid", "id", "txid"),
    "timestamp": ("timestamp", "date", "datetime", "transaction_time", "time"),
    "sender": ("sender", "sender_account_id", "from_account", "fromaccount", "account_orig", "nameorig", "originator"),
    "receiver": ("receiver", "receiver_account_id", "to_account", "toaccount", "account_dest", "namedest", "beneficiary"),
    "amount": ("amount", "tx_amount", "amount_paid", "amount_received", "transaction_amount", "value"),
    "currency": ("currency", "payment_currency", "receiving_currency"),
    "channel": ("channel", "tx_type", "payment_format", "payment_type", "type"),
    "label": ("label", "is_laundering", "islaundering", "is_fraud", "isfraud", "is_sar", "class", "target"),
    "from_bank": ("from_bank", "frombank", "sender_bank"),
    "to_bank": ("to_bank", "tobank", "receiver_bank"),
    "source_alert_id": ("source_alert_id", "alert_id"),
}


def _norm(value):
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def unique_headers(header):
    seen, result = {}, []
    for name in header:
        key = _norm(name) or "column"
        seen[key] = seen.get(key, 0) + 1
        result.append(key if seen[key] == 1 else f"{key}_{seen[key]}")
    return result


def infer_mapping(headers):
    normalized = unique_headers(headers)
    mapping = {}
    for field, choices in ALIASES.items():
        for choice in choices:
            if choice in normalized:
                mapping[field] = choice
                break
    # AMLSim commonly repeats "Account" for origin and destination.
    if "account" in normalized and "account_2" in normalized:
        mapping.setdefault("sender", "account")
        mapping.setdefault("receiver", "account_2")
    elif "account" in normalized:
        mapping.setdefault("sender", "account")
    # Prefer amount/currency pairs that correspond to each other.
    if "amount_paid" in normalized:
        mapping["amount"] = "amount_paid"
        if "payment_currency" in normalized:
            mapping["currency"] = "payment_currency"
    elif "amount_received" in normalized:
        mapping["amount"] = "amount_received"
        if "receiving_currency" in normalized:
            mapping["currency"] = "receiving_currency"
    return mapping


def inspect_csv(payload: bytes):
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded.") from exc
    reader = csv.reader(io.StringIO(text))
    try:
        originals = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV is empty.") from exc
    headers = unique_headers(originals)
    sample = []
    for _, values in zip(range(5), reader):
        if values:
            sample.append(dict(zip(headers, values)))
    return {"headers": headers, "mapping": infer_mapping(originals), "sample": sample}


def import_csv(payload: bytes, filename: str, mapping: dict | None = None, dataset_name: str | None = None,
               timestamp_kind: str = "datetime"):
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded.") from exc
    reader = csv.reader(io.StringIO(text))
    try:
        original_headers = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV is empty.") from exc
    headers = unique_headers(original_headers)
    if timestamp_kind not in {"datetime", "simulation_step"}:
        raise ValueError("timestamp_kind must be 'datetime' or 'simulation_step'.")
    inferred = infer_mapping(original_headers)
    selected = {**inferred, **(mapping or {})}
    required = ("timestamp", "sender", "receiver", "amount")
    missing = [field for field in required if not selected.get(field)]
    if missing:
        raise ValueError(f"Map required fields {', '.join(missing)}. A missing transaction_id is generated automatically. Available columns: {', '.join(headers)}")
    invalid, valid, seen = [], [], set()
    for line, values in enumerate(reader, start=2):
        if not values or not any(v.strip() for v in values):
            continue
        if len(values) != len(headers):
            invalid.append({"row": line, "error": f"Expected {len(headers)} columns; found {len(values)}."})
            continue
        raw = dict(zip(headers, values))
        def get(field, default=""):
            col = selected.get(field)
            return raw.get(col, "").strip() if isinstance(col, str) else default
        def account(field, bank_field):
            value = get(field)
            bank = get(bank_field)
            return f"{bank}:{value}" if bank and value else value
        source_id = get("transaction_id")
        dataset_key = dataset_name or filename
        stable_key = f"{dataset_key}\0{source_id}" if source_id else f"{filename}:{line}:{values}"
        canonical_id = "SRC-" + hashlib.sha256(stable_key.encode()).hexdigest()[:40]
        if canonical_id in seen:
            invalid.append({"row": line, "error": f"Duplicate transaction ID {canonical_id}; duplicate row skipped."})
            continue
        seen.add(canonical_id)
        try:
            currency_value = get("currency").strip().upper() or None
            if currency_value is not None and not re.fullmatch(r"[A-Z]{3}", currency_value):
                raise ValueError(f"Currency must be a three-letter ISO 4217 code; got {currency_value!r}.")
            raw_timestamp = get("timestamp")
            step = None
            if timestamp_kind == "simulation_step":
                if not re.fullmatch(r"\d+", raw_timestamp):
                    raise ValueError(f"Simulation step must be a non-negative integer; got {raw_timestamp!r}.")
                step = int(raw_timestamp)
                parsed_timestamp = None
            else:
                parsed_timestamp = raw_timestamp
            record = TransactionIn(transaction_id=canonical_id[:100], timestamp=parsed_timestamp,
                simulation_step=step, sender=account("sender", "from_bank"), receiver=account("receiver", "to_bank"),
                amount=get("amount"), currency=currency_value or "USD", channel=get("channel", "wire") or "wire",
                description=f"Imported from {dataset_name or filename}")
            label = get("label") or None
            valid.append({**record.model_dump(), "source_transaction_id": source_id or None, "source_label": label,
                          "label_source": "dataset" if label is not None else "none",
                          "source_dataset": dataset_key[:120], "source_row": line,
                          "source_timestamp_value": raw_timestamp, "source_alert_id": get("source_alert_id") or None,
                          "source_record": raw, "currency_missing": currency_value is None})
        except Exception as exc:
            invalid.append({"row": line, "error": str(exc)})
    return {"headers": headers, "mapping": selected, "valid": valid, "invalid_rows": invalid,
            "labelled_rows": sum(x["source_label"] is not None for x in valid)}


def parse_binary_label(value, positive_label, negative_label):
    """Map only caller-declared exact source labels to binary reference classes."""
    if not positive_label or not negative_label or positive_label == negative_label:
        return None
    value = str(value).strip()
    if value == positive_label: return 1
    if value == negative_label: return 0
    return None
