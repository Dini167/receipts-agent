"""Second evaluation: free-form questions with known right answers.

    python -m eval.run_questions_eval --version before   # model gets raw rows only
    python -m eval.run_questions_eval --version after    # days left, counts and sums done in code
    python -m eval.run_questions_eval --offline           # quick check of the scorer, no keys

Each question lists the numbers and words the answer must contain, and words it must not
contain (for example, a product whose warranty does not end in the asked window).
The data is the same made-up family as in run_eval.py, with "today" fixed to 2026-11-22.
"""

import argparse
import json
import os
import re

os.environ.setdefault("REQUESTS_PER_SECOND", "0.2")   # stay under the free per-minute limit
import tempfile
from datetime import date
from pathlib import Path

from langgraph.types import Command

from src import db
from src.graph import build_graph

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "questions.json"
STATEMENT = ROOT / "data" / "statements" / "statement_2026_11.csv"
DATASET = "receipts-agent-questions"
TODAY = date(2026, 11, 22)


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def numbers_in(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def score_answer(answer: str, expected: dict) -> tuple[int, str]:
    """1 if every needed number and word is there and no forbidden word is."""
    found = numbers_in(answer)
    missing = [n for n in expected["numbers"] if not any(abs(f - n) < 0.06 for f in found)]
    missing += [w for w in expected["words"] if w not in answer]
    extra = [w for w in expected["forbidden"] if w in answer]
    ok = not missing and not extra
    return int(ok), "" if ok else f"missing {missing}, should not mention {extra}"


def make_graph(ai, precompute: bool):
    """A database with the family's data and a checked statement, then the agent on top."""
    from tests.fake_ai import FakeAI, load_truth_into_db
    path = Path(tempfile.mkdtemp()) / "questions.db"
    with db.connect(path) as c:
        load_truth_into_db(c, db)
    setup = build_graph(FakeAI(), path, today=TODAY)      # fills checked_charges, no model needed
    cfg = {"configurable": {"thread_id": "setup"}}
    out = setup.invoke({"file_path": str(STATEMENT)}, cfg)
    while out.get("__interrupt__"):
        kind = out["__interrupt__"][0].value["type"]
        out = setup.invoke(Command(resume=[] if kind == "confirm_suspicious" else True), cfg)
    return build_graph(ai, path, today=TODAY, precompute=precompute)


def ask(graph, question: str) -> str:
    cfg = {"configurable": {"thread_id": question}, "run_name": "question"}
    return graph.invoke({"input_kind": "question", "question": question}, cfg)["answer"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["before", "after"], default="after")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    questions = load_questions()

    if args.offline:            # check the scorer with perfect made-up answers
        for q in questions:
            fake = " ".join([str(n) for n in q["numbers"]] + q["words"])
            assert score_answer(fake, q)[0] == 1, q
        print(f"scorer ok on {len(questions)} questions")
        return

    from langsmith import Client, evaluate
    from src.ai import ModelAI
    graph = make_graph(ModelAI(), precompute=args.version == "after")

    client = Client()
    if not client.has_dataset(dataset_name=DATASET):
        ds = client.create_dataset(DATASET, description="Free-form questions with known answers")
        client.create_examples(dataset_id=ds.id, examples=[
            {"inputs": {"question": q["question"]},
             "outputs": {k: q[k] for k in ("numbers", "words", "forbidden", "case")}}
            for q in questions])

    def correct_answer(outputs: dict, reference_outputs: dict) -> dict:
        score, why = score_answer(outputs["answer"], reference_outputs)
        return {"key": "correct_answer", "score": score, "comment": why}

    results = evaluate(lambda inputs: {"answer": ask(graph, inputs["question"])},
                       data=DATASET, evaluators=[correct_answer], max_concurrency=1,
                       experiment_prefix=f"questions-{args.version}",
                       metadata={"version": args.version}, client=client)
    rows = list(results)
    good = sum(r["evaluation_results"]["results"][0].score for r in rows)
    print(f"{args.version}: {good:g}/{len(rows)} correct")
    for r in rows:
        res = r["evaluation_results"]["results"][0]
        if not res.score:
            print("  wrong:", r["example"].inputs["question"], "|", res.comment)


if __name__ == "__main__":
    main()
