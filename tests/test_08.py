"""Test T08 (Retention & Delete Request Simulator) — không cần ground truth của giảng viên.

Nhãn kỳ vọng được gán TAY từ dữ liệu fixture (xem docs/tracks/T08.md):
  a0043 (raw của subj_03) và a0099 (raw của subj_07) có legal_hold  -> retain_legal_hold
  a0156 (backup của subj_11) acl=vendor-x                           -> escalate (không có quyền)
  a0075/a0079/a0083 (embedding của subj_05) origin_known=False      -> escalate
  a0211/a0212 (training_export nhiều chủ thể)                       -> không được xóa thẳng
"""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src import main as runner

FX = Path("fixtures/t08_deletion")


def _cfg(tmp_path, **params):
    p = tmp_path / "lab.yaml"
    p.write_text(yaml.safe_dump({"track": "t08", "owner": "Test Owner (DPO)", "seed": 42, "offline": True,
                                 "strict_provenance": True, "params": {"dry_run": True, **params}}))
    return str(p)


def _run(tmp_path, out_name="out", inp=FX, pipeline=None, **params):
    out = tmp_path / out_name
    args = ["--config", _cfg(tmp_path, **params), "--track", "t08", "--input", str(inp), "--output", str(out), "--offline", "--seed", "42"]
    if pipeline:
        args += ["--pipeline", pipeline]
    return runner.main(args), out


def _act(out):
    return pd.read_csv(out / "actions.csv")


def test_poc_end_to_end_and_hand_labeled_cases(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    for f in ["actions.csv", "audit_log.jsonl", "review_queue.csv", "decision.json", "decision_log.csv", "dry_run_plan.csv", "run_info.json"]:
        assert (out / f).exists(), f
    a = _act(out)
    assert not a.duplicated(["request_id", "artefact_id"]).any()
    assert set(a.action) <= {"delete", "retain_legal_hold", "escalate"}
    get = lambda aid: set(a[a.artefact_id == aid].action)
    assert get("a0043") == {"retain_legal_hold"} and get("a0099") == {"retain_legal_hold"}
    assert get("a0156") == {"escalate"}
    assert get("a0075") == {"escalate"} and get("a0079") == {"escalate"} and get("a0083") == {"escalate"}
    assert "delete" not in get("a0211") and "delete" not in get("a0212")   # export chứa chủ thể chưa yêu cầu xóa
    # không xóa nhầm: mọi dòng delete phải không dính legal hold / acl / origin lạ
    graph = {x["artefact_id"]: x for x in json.loads((FX / "data_graph.json").read_text())["artefacts"]}
    for r in a[a.action == "delete"].itertuples():
        g = graph[r.artefact_id]
        assert not g["legal_hold"] and g["origin_known"] and "data-platform" in g["acl"]
    # lineage đầy đủ: không chỉ raw — có backup, frame, face_crop, embedding, annotation bị xóa
    assert {"raw_video", "backup", "frame", "face_crop", "embedding", "annotation"} <= set(a[a.action == "delete"].type)
    # còn escalate chưa duyệt -> quyết định phải là HOLD, có reason_code + owner
    d = json.loads((out / "decision.json").read_text())
    assert d["status"] == "HOLD" and d["reason_code"] and d["owner"] == "Test Owner (DPO)"
    # audit log phủ mọi artefact có hành động
    logged = {json.loads(l)["item_id"] for l in (out / "audit_log.jsonl").read_text().splitlines()}
    assert set(a.artefact_id) <= logged


def test_idempotent_two_runs_same_actions_and_no_second_delete(tmp_path):
    rc1, o1 = _run(tmp_path, "o1")
    rc2, o2 = _run(tmp_path, "o2")
    assert rc1 == rc2 == 0
    assert (o1 / "actions.csv").read_text() == (o2 / "actions.csv").read_text()
    # thực thi mock 2 lần trên cùng thư mục: lần 2 không xóa thêm gì
    _, o = _run(tmp_path, "real", dry_run=False)
    first = json.loads((o / "run_info.json").read_text())["stats"]["executed"]
    assert first > 0
    _, o = _run(tmp_path, "real", dry_run=False)
    second = json.loads((o / "run_info.json").read_text())["stats"]["executed"]
    assert second == 0


def test_baseline_deletes_held_raw_and_misses_derived(tmp_path):
    rc, out = _run(tmp_path, "base", pipeline="src.baseline")
    assert rc == 0
    b, poc = _act(out), _act(_run(tmp_path, "poc")[1])
    assert set(b.artefact_id) >= {"a0043", "a0099"}                   # baseline xóa nhầm raw đang legal hold
    must_delete = set(map(tuple, poc[poc.action == "delete"][["request_id", "artefact_id"]].values))
    got = set(map(tuple, b[b.action == "delete"][["request_id", "artefact_id"]].values))
    assert len(got & must_delete) < 0.2 * len(must_delete)            # chỉ xóa raw, bỏ sót bản dẫn xuất


def test_review_override_flow_and_audit(tmp_path):
    rc, out = _run(tmp_path)
    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    esc = q.suggested_action == "escalate"
    q.loc[esc, ["reviewer", "reviewer_decision"]] = ["Nguyen DPO", "approve"]
    k = "DR-004|a0075"
    q.loc[q.item_id == k, ["reviewer_decision", "override_value", "review_note"]] = ["edit", "delete", "origin xác minh: embedding của subj_05"]
    q.to_csv(out / "review_queue_reviewed.csv", index=False)
    rc, out = _run(tmp_path)          # chạy lại cùng thư mục output
    assert rc == 0
    a = _act(out)
    row = a[(a.request_id == "DR-004") & (a.artefact_id == "a0075")].iloc[0]
    assert row.action == "delete" and row.reason_code == "REVIEWER_OVERRIDE" and row.reviewed_by == "Nguyen DPO"
    assert json.loads((out / "decision.json").read_text())["status"] == "GO"
    events = [json.loads(l) for l in (out / "audit_log.jsonl").read_text().splitlines()]
    assert any(e["action"].startswith("override:edit") and e["actor"] == "Nguyen DPO" for e in events)


def test_override_of_legal_hold_to_delete_is_rejected(tmp_path):
    rc, out = _run(tmp_path)
    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    q.loc[q.item_id == "DR-002|a0043", ["reviewer", "reviewer_decision", "override_value"]] = ["x", "edit", "delete"]
    q.to_csv(out / "review_queue_reviewed.csv", index=False)
    rc, _ = _run(tmp_path)
    assert rc == 2                    # lỗi dữ liệu/đầu vào rõ ràng, không im lặng


def test_review_without_reviewer_name_fails(tmp_path):
    rc, out = _run(tmp_path)
    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    q.loc[0, "reviewer_decision"] = "approve"
    q.to_csv(out / "review_queue_reviewed.csv", index=False)
    assert _run(tmp_path)[0] == 2


def test_tampered_input_fails_provenance_check(tmp_path):
    bad = tmp_path / "fx"
    shutil.copytree(FX, bad)
    g = bad / "data_graph.json"
    g.write_text(g.read_text()[:-200])          # cắt cụt JSON -> hash sai
    rc, _ = _run(tmp_path, inp=bad)
    assert rc == 2


def test_other_tracks_still_not_implemented(tmp_path):
    rc = runner.main(["--track", "t02", "--output", str(tmp_path / "x"), "--offline"])
    assert rc == 3
