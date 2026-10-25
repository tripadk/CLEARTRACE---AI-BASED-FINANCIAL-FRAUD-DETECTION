from app.services.dataset_import import import_csv, inspect_csv


def test_ibm_amlsim_headers_are_inferred_and_source_labels_preserved():
    payload = (b"Timestamp,From Bank,Account,To Bank,Account,Amount Paid,Payment Currency,Payment Format,Is Laundering\n"
               b"2026-01-01T00:00:00Z,1,1001,2,2002,425.5,USD,Wire,1\n")
    inspected = inspect_csv(payload)
    assert inspected["mapping"]["sender"] == "account"
    assert inspected["mapping"]["receiver"] == "account_2"
    result = import_csv(payload, "amlsim.csv")
    assert len(result["valid"]) == 1
    assert result["valid"][0]["source_label"] == "1"
    assert result["valid"][0]["source_transaction_id"] is None
    assert result["valid"][0]["sender"] == "1:1001"
    assert result["labelled_rows"] == 1


def test_missing_labels_remain_unlabeled_and_invalid_rows_are_reported():
    payload = (b"tx_id,timestamp,from_account,to_account,amount,currency\n"
               b"x1,2026-01-01T00:00:00Z,A,B,100,USD\n"
               b"x2,bad-time,C,D,not-money,USD\n")
    result = import_csv(payload, "unlabeled.csv")
    assert result["valid"][0]["source_transaction_id"] == "x1"
    assert result["valid"][0]["label_source"] == "none"
    assert result["valid"][0]["source_label"] is None
    assert result["invalid_rows"] and result["invalid_rows"][0]["row"] == 3


def test_explicit_mapping_overrides_inferred_fields_and_duplicate_rows_skip():
    payload = (b"id,when,origin,destination,usd,label\n"
               b"same,2026-01-01T00:00:00Z,A,B,100,0\n"
               b"same,2026-01-01T00:01:00Z,C,D,200,1\n")
    result = import_csv(payload, "mapped.csv", {"transaction_id": "id", "timestamp": "when", "sender": "origin",
                        "receiver": "destination", "amount": "usd", "label": "label"})
    assert len(result["valid"]) == 1
    assert result["invalid_rows"][0]["error"].startswith("Duplicate transaction ID")


def test_missing_currency_is_flagged_and_malformed_currency_is_invalid():
    payload = (b"tx_id,timestamp,from_account,to_account,amount,currency\n"
               b"unknown,2026-01-01T00:00:00Z,A,B,100,\n"
               b"bad,2026-01-01T00:01:00Z,C,D,100,US\n")
    result = import_csv(payload, "currency.csv")
    assert result["valid"][0]["currency_missing"] is True
    assert result["invalid_rows"][0]["row"] == 3
    assert "three-letter ISO 4217" in result["invalid_rows"][0]["error"]


def test_zero_amount_simulation_transactions_are_preserved():
    payload = b"TX_ID,SENDER_ACCOUNT_ID,RECEIVER_ACCOUNT_ID,TX_TYPE,TX_AMOUNT,TIMESTAMP,IS_FRAUD,ALERT_ID\nz1,A,B,TRANSFER,0.0,0,False,-1\n"
    result = import_csv(payload, "zero.csv", dataset_name="zero", timestamp_kind="simulation_step")
    assert len(result["valid"]) == 1
    assert result["valid"][0]["amount"] == 0
    assert result["valid"][0]["simulation_step"] == 0
