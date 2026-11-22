"""Run a LangSmith experiment on the 40 labeled charges.

    python -m eval.run_eval --version baseline     # experiment 1 (before)
    python -m eval.run_eval --version improved     # experiment 2 (after)
    python -m eval.run_eval --offline              # quick check with no keys and no LangSmith

baseline: short "same business?" prompt, and handwritten lines matched by amount only.
improved: prompt with rules and examples, plus a check that the handwritten line fits the store.

The database is filled with the correct receipts and handwritten lines, so the score
measures the matching only (reading receipts is checked separately).
"""

import argparse
import csv
import os

# many requests in a row: stay under the free plan's per-minute limit (must be set before src.llm loads)
os.environ.setdefault("REQUESTS_PER_SECOND", "0.2")
import tempfile
from collections import Counter
from pathlib import Path

from langgraph.types import Command

from src import db
from src.graph import build_graph

ROOT = Path(__file__).resolve().parent.parent
STATEMENT = ROOT / "data" / "statements" / "statement_2026_11.csv"
LABELS = ROOT / "eval" / "statement_labels.csv"
DATASET = "receipts-agent-charges"


def load_labels() -> list[dict]:
    with open(LABELS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_agent(ai) -> dict[str, dict]:
    """Run the whole statement flow once and return charge_id -> result."""
    import sys
    sys.path.insert(0, str(ROOT))
    from tests.fake_ai import load_truth_into_db

    path = Path(tempfile.mkdtemp()) / "eval.db"
    with db.connect(path) as c:
        load_truth_into_db(c, db)
    graph = build_graph(ai, path)
    cfg = {"configurable": {"thread_id": "eval"}, "run_name": "statement-check"}
    out = graph.invoke({"file_path": str(STATEMENT)}, cfg)
    while out.get("__interrupt__"):          # answer every stop automatically
        kind = out["__interrupt__"][0].value["type"]
        out = graph.invoke(Command(resume=[] if kind == "confirm_suspicious" else True), cfg)
    return out["results"]


def ensure_dataset(client):
    """Upload the 40 labeled charges to LangSmith once."""
    if client.has_dataset(dataset_name=DATASET):
        return
    rows = {r["charge_id"]: r for r in csv.DictReader(open(STATEMENT, encoding="utf-8"))}
    ds = client.create_dataset(DATASET, description="40 credit card charges with the right status")
    client.create_examples(dataset_id=ds.id, examples=[
        {"inputs": rows[l["charge_id"]],
         "outputs": {"status": l["expected_status"], "case": l["case"]}}
        for l in load_labels()])


def status_correct(outputs: dict, reference_outputs: dict) -> dict:
    """Evaluator: 1 if the agent gave the right status for this charge."""
    return {"key": "correct_status", "score": int(outputs["status"] == reference_outputs["status"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["baseline", "improved"], default="improved")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    if args.offline:
        from tests.fake_ai import FakeAI
        results = run_agent(FakeAI())
    else:
        from src.ai import ModelAI
        results = run_agent(ModelAI(improved=args.version == "improved"))

    labels = load_labels()
    wrong = [(l["charge_id"], l["case"], results[l["charge_id"]]["status"], l["expected_status"])
             for l in labels if results[l["charge_id"]]["status"] != l["expected_status"]]
    print(f"{args.version}: {len(labels) - len(wrong)}/{len(labels)} correct")
    print(Counter(r["status"] for r in results.values()))
    for w in wrong:
        print("  wrong:", *w)

    if args.offline:
        return

    from langsmith import Client, evaluate
    client = Client()
    ensure_dataset(client)
    evaluate(lambda inputs: {"status": results[inputs["charge_id"]]["status"],
                             "reason": results[inputs["charge_id"]]["reason"]},
             data=DATASET, evaluators=[status_correct],
             experiment_prefix=args.version, metadata={"version": args.version},
             client=client)


if __name__ == "__main__":
    main()
