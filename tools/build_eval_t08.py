"""Một lệnh: chạy baseline + PoC, chấm bằng ĐÁP ÁN NHÓM TỰ GÁN, sinh metrics + bảng so sánh.

    python -m tools.build_eval_t08

Ground truth ở đây KHÔNG phải của giảng viên: reports/self_check/gold_t08.csv (52 dòng gán tay trên fixture gốc).
Vì gold chỉ phủ một phần, dự đoán được LỌC về đúng các cặp (request_id, artefact_id) có trong gold trước khi chấm
(nếu không, evaluator sẽ coi mọi dòng delete ngoài gold là "xóa nhầm" giả).

Sinh ra (đường dẫn gt được ghi trong extra.gt của JSON để người chấm thấy rõ nguồn đáp án):
    reports/metrics_baseline.json, reports/metrics_poc.json
    reports/slices_baseline.csv,   reports/slices_poc.csv
    reports/table1_baseline_vs_poc.md
    (kèm bộ kịch bản tự tạo: reports/self_check/self_check_selfmade_*.json qua tools.selfcheck_t08)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD = "reports/self_check/gold_t08.csv"


def sh(*args: str) -> None:
    r = subprocess.run([sys.executable, *args], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"lệnh thất bại ({r.returncode}): python {' '.join(args)}")


def main() -> int:
    gold = pd.read_csv(ROOT / GOLD)
    keys = set(zip(gold.request_id, gold.artefact_id))
    for name, mod in (("baseline", "src.baseline"), ("poc", "src.pipeline")):
        out = ROOT / "out" / name
        sh("-m", "src.main", "--config", "configs/lab.yaml", "--track", "t08", "--pipeline", mod, "--output", f"out/{name}",
           "--run-name", name, "--offline", "--seed", "42")
        pred = pd.read_csv(out / "actions.csv")
        pred[[k in keys for k in zip(pred.request_id, pred.artefact_id)]].to_csv(out / "actions_sample.csv", index=False)
        sh("-m", "src.evaluate", "--track", "t08", "--gt", GOLD, "--pred", f"out/{name}/actions_sample.csv", "--run-name", name,
           "--out", f"reports/metrics_{name}.json", "--slices-out", f"reports/slices_{name}.csv")
    sh("-m", "src.compare", "reports/metrics_baseline.json", "reports/metrics_poc.json", "--out", "reports/table1_baseline_vs_poc.md")
    sh("-m", "tools.selfcheck_t08")   # bộ kịch bản tự tạo (đáp án đầy đủ)
    print("\nXong. Xem reports/table1_baseline_vs_poc.md và reports/self_check/*.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
