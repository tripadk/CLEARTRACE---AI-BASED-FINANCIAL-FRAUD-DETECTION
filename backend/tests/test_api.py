from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.transaction import Transaction


def test_demo_dashboard_alert_review_and_graph_flow():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            loaded = client.post("/api/demo/load")
            assert loaded.status_code == 200
            assert loaded.json()["inserted"] == 99

            dashboard = client.get("/api/dashboard").json()
            assert dashboard["transaction_count"] == 99
            assert dashboard["total_volume"] > 0

            graph = client.get("/api/graph").json()
            assert graph["nodes"]
            assert graph["edges"]

            alerts = client.get("/api/alerts").json()
            if alerts:
                transaction_id = alerts[0]["transaction_id"]
                updated = client.patch(f"/api/alerts/{transaction_id}/status?status=reviewing")
                assert updated.status_code == 200
                assert updated.json()["review_status"] == "reviewing"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_csv_upload_validation_message():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            result = client.post("/api/transactions/upload", files={"file": ("bad.csv", b"name,value\na,1", "text/csv")})
            assert result.status_code == 422
            assert "transaction_id" in result.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_public_dataset_import_preserves_labels_and_metrics_require_confirmation():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    csv_data = "tx_id,timestamp,from_account,to_account,amount,is_laundering\n" + "".join(
        f"IBM-{i},2026-01-{1 + i // 24:02d}T{i % 24:02d}:00:00Z,A{i},B{i},{100+i},{i % 2}\n" for i in range(20))
    try:
        with TestClient(app) as client:
            preview = client.post("/api/transactions/inspect", files={"file": ("ibm.csv", csv_data.encode(), "text/csv")})
            assert preview.status_code == 200
            assert preview.json()["mapping"]["label"] == "is_laundering"
            imported = client.post("/api/transactions/upload", files={"file": ("ibm.csv", csv_data.encode(), "text/csv")})
            assert imported.status_code == 200, imported.text
            assert imported.json()["labelled_rows"] == 20
            tx = client.get("/api/transactions?q=IBM-0").json()["items"][0]
            assert tx["source_transaction_id"] == "IBM-0"
            assert tx["source_label"] == "0" and tx["label_source"] == "dataset"
            assert tx["risk_score"] >= 0 and "evaluation_eligible" in tx
            assert client.get("/api/evaluation").json()["available"] is False
            evaluation = client.get("/api/evaluation?labels_verified=true&positive_label=1&negative_label=0").json()
            assert evaluation["available"] is True
            assert set(("precision", "recall", "f1", "false_positive_rate")) <= evaluation.keys()
            assert evaluation["evaluated_sample_count"] == 6
            assert evaluation["positive_class_count"] == 3
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_import_scope_combines_graph_across_datasets_and_currency_totals_are_safe():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    def override_db():
        db = TestingSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            one = "tx_id,timestamp,from_account,to_account,amount,currency\nA1,2026-01-01T00:00:00Z,A,B,100,USD\n"
            two = "tx_id,timestamp,from_account,to_account,amount,currency\nB1,2026-01-01T00:01:00Z,B,C,100,USD\nC1,2026-01-01T00:02:00Z,C,A,100,USD\n"
            assert client.post("/api/transactions/upload", data={"dataset_name":"first"}, files={"file":("one.csv",one.encode(),"text/csv")}).json()["inserted"] == 1
            result = client.post("/api/transactions/upload", data={"dataset_name":"second"}, files={"file":("two.csv",two.encode(),"text/csv")}).json()
            assert result["inserted"] == 2
            final = client.get("/api/transactions?q=C1").json()["items"][0]
            assert "circular_transfer" not in final["contributing_signals"]
            combined = client.post("/api/transactions/upload", data={"dataset_name":"second", "analysis_scope":"all_imported"}, files={"file":("two.csv",two.encode(),"text/csv")}).json()
            assert combined["inserted"] == 0 and combined["skipped_duplicates"] == 2
            final = client.get("/api/transactions?q=C1").json()["items"][0]
            assert "circular_transfer" in final["contributing_signals"]
            assert len(final["supporting_transaction_ids"]) >= 3
            assert client.get("/api/dashboard").json()["total_volume_currency"] == "USD"
            mixed = "tx_id,timestamp,from_account,to_account,amount,currency\nX,2026-01-02T00:00:00Z,X,Y,100,EUR\n"
            client.post("/api/transactions/upload", data={"dataset_name":"third", "analysis_scope":"all_imported"}, files={"file":("three.csv",mixed.encode(),"text/csv")})
            dashboard = client.get("/api/dashboard").json()
            assert dashboard["total_volume"] is None and dashboard["currency_warning"]
            assert dashboard["currency_totals"]["EUR"] == 100
            missing = "tx_id,timestamp,from_account,to_account,amount\nU,2026-01-03T00:00:00Z,U,V,50\n"
            missing_import = client.post("/api/transactions/upload", data={"dataset_name":"unknown_currency"}, files={"file":("missing.csv",missing.encode(),"text/csv")}).json()
            unknown_tx = client.get("/api/transactions?q=U").json()["items"][0]
            assert unknown_tx["currency_missing"] is True and missing_import["currency_warning"]
            assert client.get("/api/dashboard").json()["total_volume"] is None
    finally:
        app.dependency_overrides.clear(); engine.dispose()


def test_evaluation_uses_only_explicit_exact_labels_and_reports_safe_counts():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    def override_db():
        db = TestingSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            empty = client.get("/api/evaluation?labels_verified=true&positive_label=P&negative_label=N").json()
            assert not empty["available"] and empty["evaluated_sample_count"] == 0
            db = TestingSession()
            examples = (("P", 80), ("P", 20), ("N", 70), ("N", 10)) * 2
            for i, (label, score) in enumerate(examples):
                db.add(Transaction(transaction_id=f"eval-{i}", timestamp=__import__("datetime").datetime(2026, 1, i + 1),
                    sender="A", receiver="B", amount=10, currency="USD", source_label=label,
                    label_source="dataset", source_dataset="verified", validation_eligible=i < 4,
                    evaluation_eligible=i >= 4,
                    risk_score=score, alert_threshold=40))
            db.commit(); db.close()
            arbitrary = client.get("/api/evaluation?labels_verified=true&positive_label=1&negative_label=0").json()
            assert not arbitrary["available"] and arbitrary["evaluated_sample_count"] == 0
            result = client.get("/api/evaluation?labels_verified=true&positive_label=P&negative_label=N&threshold=40").json()
            assert result["available"]
            assert (result["evaluated_sample_count"], result["positive_class_count"]) == (4, 2)
            assert result["validation_sample_count"] == 4
            assert (result["baselines"]["existing_detector"]["precision"], result["baselines"]["existing_detector"]["recall"],
                    result["baselines"]["existing_detector"]["f1"], result["baselines"]["existing_detector"]["false_positive_rate"]) == (.5, .5, .5, .5)
            selected_threshold = result["validation_selected_threshold"]
            db = TestingSession()
            for tx in db.query(Transaction).filter(Transaction.evaluation_eligible.is_(True)):
                tx.source_label = "N" if tx.source_label == "P" else "P"
            db.commit(); db.close()
            changed_holdout = client.get("/api/evaluation?labels_verified=true&positive_label=P&negative_label=N&threshold=40").json()
            assert changed_holdout["validation_selected_threshold"] == selected_threshold
    finally:
        app.dependency_overrides.clear(); engine.dispose()


def test_amlsim_simulation_import_is_idempotent_and_preserves_demo_and_labels():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    def override_db():
        db = TestingSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    header = "TX_ID,SENDER_ACCOUNT_ID,RECEIVER_ACCOUNT_ID,TX_TYPE,TX_AMOUNT,TIMESTAMP,IS_FRAUD,ALERT_ID\n"
    body = "".join(f"id{i},A{i%5},B{i%7},TRANSFER,{100+i},{step},{str(i%10==0)},alert-{i%2}\n"
                   for i, step in enumerate([i // 10 for i in range(200)]))
    payload = (header + body).encode()
    try:
        with TestClient(app) as client:
            assert client.post("/api/demo/load").json()["inserted"] == 99
            data = {"dataset_name": "AMLSim integration fixture", "timestamp_kind": "simulation_step",
                    "detection_config": '{"rapid_window_steps":1,"rapid_min_transfers":3}'}
            uploaded = client.post("/api/transactions/upload", data=data, files={"file": ("sample.csv", payload, "text/csv")})
            assert uploaded.status_code == 200, uploaded.text
            assert uploaded.json()["inserted"] == 200
            tx = client.get("/api/transactions?q=id0").json()["items"][0]
            assert tx["timestamp"] is None and tx["simulation_step"] == 0
            assert tx["source_timestamp_value"] == "0" and tx["source_alert_id"] == "alert-0"
            assert tx["source_transaction_id"] == "id0" and tx["source_label"] == "True"
            assert tx["label_source"] == "dataset"
            again = client.post("/api/transactions/upload", data=data, files={"file": ("sample.csv", payload, "text/csv")})
            assert again.status_code == 200 and again.json()["inserted"] == 0
            assert client.get("/api/dashboard").json()["transaction_count"] == 299
            metrics = client.get("/api/evaluation?labels_verified=true&positive_label=True&negative_label=False").json()
            assert metrics["available"] and metrics["evaluation_type"].startswith("synthetic AMLSim evaluation")
            assert metrics["evaluated_sample_count"] == metrics["positive_class_count"] + metrics["negative_class_count"]
            assert metrics["positive_class_count"] > 0 and metrics["negative_class_count"] > 0
            assert "positive_class_proportion" in metrics and "false_positive_rate" in metrics
    finally:
        app.dependency_overrides.clear(); engine.dispose()
