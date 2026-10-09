"""Frozen region/fragment contracts, evaluated with real SQLite retrieval and no LLM."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch

from offline_evaluation import _database, retrieval_metrics
from app.agent.runtime import AgentRuntime


def run(dataset, output):
    if output.exists():
        raise ValueError("Use a fresh output directory")
    frozen = dataset.read_bytes()
    data = json.loads(frozen)
    engine, db = _database(data["notes"])
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("network")
        raise RuntimeError("Regional evaluation forbids network")

    results = []
    try:
        with patch.object(socket.socket, "connect", blocked), patch.object(socket, "create_connection", blocked):
            for case in data["cases"]:
                source = case["input"]
                rows = AgentRuntime._search_knowledge(db, source["user_id"], source["city"], source["keywords"], kind=source["kind"])
                keys = [f"{row.id}:{row.source_start}" for row in rows]
                results.append({**case, "prediction": keys, "excerpts": [row.model_dump(mode="json") for row in rows],
                                "pass": set(keys) == set(case["gold"]), "metrics": retrieval_metrics(keys, case["gold"])})
    finally:
        db.close()
        engine.dispose()
    assert dataset.read_bytes() == frozen
    summary = {"n": len(results), "passed": sum(row["pass"] for row in results), "real_llm_calls": 0,
               "network_attempts": len(attempts), "dataset_sha256": hashlib.sha256(frozen).hexdigest(),
               "scope": data["annotation"], "results": results}
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "frozen_cases.json").write_bytes(frozen)
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("region_cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.dataset, args.output)
