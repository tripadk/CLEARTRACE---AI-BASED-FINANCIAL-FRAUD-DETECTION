from datetime import datetime, timedelta, timezone
import random


def demo_transactions(seed: int = 2026, count: int = 90) -> list[dict]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    accounts = [f"ACCT-{i:03}" for i in range(1, 19)]
    rows = []
    for i in range(count):
        sender, receiver = rng.sample(accounts, 2)
        amount = round(rng.uniform(220, 6200), 2)
        when = now - timedelta(hours=rng.randrange(24 * 14), minutes=rng.randrange(60))
        rows.append({"transaction_id": f"DEMO-{i+1:04}", "timestamp": when.isoformat(), "sender": sender,
                     "receiver": receiver, "amount": amount, "currency": "USD",
                     "channel": rng.choice(["wire", "ach", "card", "crypto"]), "description": "Routine account transfer"})
    # Deliberate loop, rapid burst, and repeated low-value transfers for demonstrations.
    base = now - timedelta(hours=8)
    for j, (a, b) in enumerate([("ACCT-101", "ACCT-102"), ("ACCT-102", "ACCT-103"), ("ACCT-103", "ACCT-101")]):
        rows.append({"transaction_id": f"DEMO-CYCLE-{j+1}", "timestamp": (base + timedelta(minutes=j*18)).isoformat(),
                     "sender": a, "receiver": b, "amount": 6800 + j*500, "currency": "USD", "channel": "wire",
                     "description": "Demonstration circular-path transfer"})
    for j in range(6):
        rows.append({"transaction_id": f"DEMO-BURST-{j+1}", "timestamp": (base + timedelta(minutes=j*7)).isoformat(),
                     "sender": "ACCT-104", "receiver": f"ACCT-{105+j:03}", "amount": 420 + j*13,
                     "currency": "USD", "channel": "ach", "description": "Demonstration rapid transfer"})
    return rows
