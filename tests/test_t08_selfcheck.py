"""Tự kiểm T08 bằng đáp án do nhóm tự gán (reports/self_check/) — không cần gt/ của giảng viên."""
from pathlib import Path

import pandas as pd
import pytest

from src import main as runner

SUITES = [
    ("fixtures/t08_deletion", "reports/self_check/gold_t08.csv"),       # gán tay một phần
    ("fixtures/t08_selfmade", "reports/self_check/gold_selfmade.csv"),  # kịch bản tự tạo, đầy đủ
]


def _run(tmp_path, inp, pipeline="src.pipeline"):
    out = tmp_path / "out"
    rc = runner.main(["--config", "configs/lab.yaml", "--track", "t08", "--input", inp, "--pipeline", pipeline,
                      "--output", str(out), "--offline", "--seed", "42"])
    assert rc == 0
    return pd.read_csv(out / "actions.csv")


@pytest.mark.parametrize("inp,gold_path", SUITES)
def test_poc_matches_self_made_gold(tmp_path, inp, gold_path):
    gold = pd.read_csv(gold_path)
    pred = _run(tmp_path, inp)
    m = gold.merge(pred[["request_id", "artefact_id", "action"]], on=["request_id", "artefact_id"], how="left")
    wrong = m[m.action != m.expected_action]
    assert wrong.empty, wrong[["request_id", "artefact_id", "expected_action", "action", "why"]].to_string()
    keys = set(zip(gold.request_id, gold.artefact_id))
    stray = [r for r in pred[pred.action == "delete"].itertuples() if (r.request_id, r.artefact_id) not in keys]
    if inp.endswith("selfmade"):          # gold đầy đủ -> không được xóa thứ gì ngoài gold
        assert not stray


def test_selfmade_baseline_makes_false_delete_on_unverified_request(tmp_path):
    pred = _run(tmp_path, "fixtures/t08_selfmade", "src.baseline")
    hit = pred[(pred.request_id == "R-S3") & (pred.artefact_id == "c01")]
    assert len(hit) == 1 and hit.iloc[0].action == "delete"    # baseline xóa dù chưa xác minh danh tính
