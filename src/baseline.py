"""Baseline T08 (cố tình ngây thơ): với mỗi yêu cầu, "xóa file raw theo tên file", không truy lineage,
không xét legal hold / acl / origin / nhiều chủ thể.

    python -m src.main --track t08 --pipeline src.baseline --output out/baseline --run-name baseline --offline --seed 42
    python -m src.evaluate --track t08 --pred out/baseline/actions.csv --run-name baseline --out reports/metrics_baseline.json
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.io import read_json
from .metrics.tracks import get_track


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    arts = read_json(ctx.input_dir / "data_graph.json")["artefacts"]
    requests = read_json(ctx.input_dir / "requests.json")
    rows = []
    for req in requests:
        for a in arts:
            if a["type"] == "raw_video" and req["subject_id"] in a.get("filename", ""):
                rows.append({"request_id": req["request_id"], "artefact_id": a["artefact_id"], "action": "delete"})
                ctx.audit.log(actor="baseline", action="delete", item_id=a["artefact_id"], request_id=req["request_id"])
    pd.DataFrame(rows, columns=spec.pred_columns).to_csv(ctx.out(spec.pred_file), index=False)
    ctx.stats["n_items"] = len(rows)
    write_decision(Decision(status="HOLD", reason_code="BASELINE_ONLY", reason="Naive filename-delete baseline: never release on this",
                            owner=ctx.config.get("owner", "baseline"), scope="t08", evidence=[str(ctx.out(spec.pred_file))]),
                   ctx.out("decision.json"), ctx.out("decision_log.csv"))
