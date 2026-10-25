"""Create a reproducible, uniform reservoir sample from AMLSim transactions.

The source CSV is read once in streaming mode. Original field strings, including
simulation-step timestamps and labels, are retained without transformation.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "100Kvertices-10Medges" / "transactions.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "transactions_sample_50000.csv"
REQUIRED = {
    "TX_ID", "SENDER_ACCOUNT_ID", "RECEIVER_ACCOUNT_ID", "TX_TYPE",
    "TX_AMOUNT", "TIMESTAMP", "IS_FRAUD", "ALERT_ID",
}


def create_sample(source: Path, output: Path, sample_size: int = 50_000,
                  seed: int = 42, overwrite: bool = False) -> dict:
    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    manifest_path = output.with_suffix(".manifest.json")
    resolved_source = source.resolve()
    if output.resolve() == resolved_source or manifest_path.resolve() == resolved_source:
        raise ValueError("Generated outputs must not replace the source CSV")
    if not overwrite and (output.exists() or manifest_path.exists()):
        raise FileExistsError(
            f"Output already exists: {output} (or {manifest_path}); pass --overwrite to replace generated outputs."
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    reservoir: list[tuple[int, list[str]]] = []
    total_rows = 0
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(64 * 1024)
        if not sample:
            raise ValueError("Source CSV is empty")
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        stream.seek(0)
        reader = csv.reader(stream, dialect)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("Source CSV is empty") from exc
        missing = REQUIRED.difference(header)
        if missing:
            raise ValueError(f"Source CSV is missing required columns: {', '.join(sorted(missing))}")
        width = len(header)
        for row in reader:
            if len(row) != width:
                raise ValueError(f"Malformed CSV row near data row {total_rows + 1}: expected {width} fields, found {len(row)}")
            total_rows += 1
            entry = (total_rows, row)
            if total_rows <= sample_size:
                reservoir.append(entry)
            else:
                slot = rng.randrange(total_rows)
                if slot < sample_size:
                    reservoir[slot] = entry

    if total_rows < sample_size:
        raise ValueError(f"Source has only {total_rows} data rows; requested {sample_size}")

    # Restore input order after reservoir selection; values remain source values.
    reservoir.sort(key=lambda item: item[0])
    label_counts = Counter()
    timestamps = Counter()
    tx_ids = set()
    with output.open("w", encoding="utf-8", newline="") as dest:
        writer = csv.writer(dest, dialect)
        writer.writerow(header)
        for _, row in reservoir:
            tx_id = row[header.index("TX_ID")]
            if tx_id in tx_ids:
                raise ValueError(f"Duplicate TX_ID in selected sample: {tx_id}")
            tx_ids.add(tx_id)
            label_counts[row[header.index("IS_FRAUD")]] += 1
            timestamps[row[header.index("TIMESTAMP")]] += 1
            writer.writerow(row)

    result = {
        "source": str(source),
        "output": str(output),
        "delimiter": dialect.delimiter,
        "method": "Algorithm R uniform reservoir sample; one streaming pass; output restored to source row order",
        "seed": seed,
        "source_data_rows": total_rows,
        "sample_data_rows": len(reservoir),
        "label_counts": dict(sorted(label_counts.items())),
        "label_proportions": {key: round(value / len(reservoir), 8) for key, value in sorted(label_counts.items())},
        "timestamp_values": dict(sorted(timestamps.items(), key=lambda pair: int(pair[0]))),
        "unique_transaction_ids": len(tx_ids),
    }
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true", help="replace a previously generated sample and manifest")
    args = parser.parse_args()
    print(json.dumps(create_sample(args.source, args.output, args.sample_size, args.seed, args.overwrite), indent=2))


if __name__ == "__main__":
    main()
