"""Tự kiểm thử T08 bằng đáp án do NHÓM tự gán (không phải ground truth của giảng viên).

    python -m tools.selfcheck_t08

Hai bộ:
  real      fixtures/t08_deletion + reports/self_check/gold_t08.csv   (gán tay một phần ~50 dòng)
  selfmade  fixtures/t08_selfmade + reports/self_check/gold_selfmade.csv (kịch bản tự tạo, đáp án đầy đủ)

Với bộ `real` (gold chỉ phủ một phần) ta LỌC dự đoán về đúng các cặp có trong gold trước khi chấm.
Lý do: evaluator coi mọi dòng `delete` nằm ngoài gold là "xóa nhầm"; nếu không lọc sẽ ra false-delete giả.
Kết quả ghi vào reports/self_check/self_check_<bộ>_<baseline|poc>.json (KHÔNG phải metrics_*.json chính thức).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SUITES = [
    # (tên, input, gold, lọc theo gold?)
    ("real", "fixtures/t08_deletion", "reports/self_check/gold_t08.csv", True),
    ("selfmade", "fixtures/t08_selfmade", "reports/self_check/gold_selfmade.csv", False),
]


def sh(args: list[str]) -> int:
    return subprocess.run([sys.executable, *args], cwd=ROOT).returncode


def main() -> int:
    bad = 0
    for name, inp, gold_rel, filt in SUITES:
        gold = pd.read_csv(ROOT / gold_rel)
        for pipe, mod in (("baseline", "src.baseline"), ("poc", "src.pipeline")):
            out = ROOT / "out" / "selfcheck" / name / pipe
            print(f"\n{'=' * 70}\n[{name}/{pipe}] input={inp} gold={gold_rel} ({len(gold)} dòng)\n{'=' * 70}")
            rc = sh(["-m", "src.main", "--config", "configs/lab.yaml", "--track", "t08", "--input", inp, "--pipeline", mod,
                     "--output", str(out), "--run-name", pipe, "--offline", "--seed", "42"])
            if rc != 0:
                print(f"!! src.main trả về mã {rc}")
                bad += 1
                continue
            pred = pd.read_csv(out / "actions.csv")
            if filt:
                keys = set(zip(gold.request_id, gold.artefact_id))
                pred = pred[[k in keys for k in zip(pred.request_id, pred.artefact_id)]]
            sample = out / "actions_sample.csv"   # cùng thư mục với audit_log.jsonl (evaluator đọc audit ở đó)
            pred.to_csv(sample, index=False)
            sh(["-m", "src.evaluate", "--track", "t08", "--gt", str(ROOT / gold_rel), "--pred", str(sample),
                "--run-name", pipe, "--out", str(ROOT / "reports" / "self_check" / f"self_check_{name}_{pipe}.json")])
            m = gold.merge(pred[["request_id", "artefact_id", "action"]], on=["request_id", "artefact_id"], how="left")
            wrong = m[m.action.fillna("(thiếu dòng)") != m.expected_action]
            stray = pred[(pred.action == "delete") & ~pd.Series([k in set(zip(gold.request_id, gold.artefact_id)) for k in zip(pred.request_id, pred.artefact_id)], index=pred.index)]
            print(f"-> khớp {len(m) - len(wrong)}/{len(m)} dòng gold; delete ngoài phạm vi gold: {len(stray)}")
            if len(wrong):
                print(wrong[["request_id", "artefact_id", "expected_action", "action", "why"]].to_string(index=False))
            if pipe == "poc" and (len(wrong) or len(stray)):
                bad += 1
    print("\nKẾT LUẬN:", "PoC khớp toàn bộ gold" if bad == 0 else f"có {bad} bộ chưa khớp (xem chi tiết ở trên)")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
