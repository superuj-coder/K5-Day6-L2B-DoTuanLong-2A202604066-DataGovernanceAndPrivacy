"""Sinh bộ dữ liệu TỰ TẠO để tự kiểm thử T08 (không phải ground truth của giảng viên).

    python -m tools.make_selfmade_t08

Tạo:
    fixtures/t08_selfmade/{data_graph.json, requests.json, manifest.csv}
    reports/self_check/gold_selfmade.csv     (nhãn kỳ vọng)

QUAN TRỌNG: nhãn kỳ vọng được viết CÙNG LÚC với từng artefact (tham số `exp`) theo chính sách đã chốt
(chưa xác minh danh tính > legal hold > acl > origin > nhiều chủ thể > delete; legal hold chỉ áp cho chính
artefact bị hold; dùng chung chỉ xóa khi mọi chủ thể đều có yêu cầu). Nhãn KHÔNG sinh từ code của PoC.
Mỗi kịch bản S1..S10 kiểm một tình huống khó; xem cột `why` trong gold.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from src.common.manifest import build_manifest, write_manifest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "t08_selfmade"
GOLD = ROOT / "reports" / "self_check" / "gold_selfmade.csv"
DP = ["data-platform"]

arts: list[dict] = []
requests: list[dict] = []
gold: list[tuple] = []   # (request_id, artefact_id, expected_action, why)


def req(rid: str, subject: str, verified: bool = True) -> str:
    n = len(requests)
    requests.append({"request_id": rid, "subject_id": subject, "received_at": f"2026-11-{1 + n:02d}T09:00:00+07:00",
                     "deadline": f"2026-12-{1 + n:02d}T09:00:00+07:00", "channel": "app", "identity_verified": verified})
    return rid


def add(aid: str, typ: str, subjects: list[str], parents: list[str], exp: dict, why: str,
        hold: str | None = None, acl: list[str] | None = None, origin: bool = True) -> None:
    kind_dir = {"raw_video": "raw", "backup": "glacier", "embedding": "vector-db", "annotation": "labels", "training_export": "exports"}.get(typ, "lake")
    a = {"artefact_id": aid, "type": typ, "subject_ids": subjects, "parent_ids": parents, "uri": f"mock://{kind_dir}/{typ}/{aid}",
         "owner": "data-platform", "acl": acl or DP, "legal_hold": hold, "origin_known": origin, "created_at": "2026-06-01"}
    if typ == "raw_video":
        a["filename"] = f"drive_{subjects[0]}_000.mp4"
    arts.append(a)
    for rid, label in exp.items():
        gold.append((rid, aid, label, why))


D, H, E = "delete", "retain_legal_hold", "escalate"

# S1 — chuỗi đơn giản + training_export có người ngoài (s_z) chưa yêu cầu
r = req("R-S1", "s_a")
add("a001", "raw_video", ["s_a"], [], {r: D}, "S1 raw đơn giản")
add("a002", "backup", ["s_a"], ["a001"], {r: D}, "S1 backup")
add("a003", "frame", ["s_a"], ["a001"], {r: D}, "S1 frame")
add("a004", "face_crop", ["s_a"], ["a003"], {r: D}, "S1 face_crop")
add("a005", "embedding", ["s_a"], ["a004"], {r: D}, "S1 embedding")
add("a006", "annotation", ["s_a"], ["a003"], {r: D}, "S1 annotation")
add("x01", "training_export", ["s_a", "s_z"], ["a004"], {r: E}, "S1 export chứa s_z (không yêu cầu) -> không được xóa nguyên khối")

# S2 — legal hold nằm trên frame (không phải raw); bản dẫn xuất của frame vẫn xóa (hold_scope=self)
r = req("R-S2", "s_b")
add("b01", "raw_video", ["s_b"], [], {r: D}, "S2 raw không hold")
add("b05", "backup", ["s_b"], ["b01"], {r: D}, "S2 backup")
add("b02", "frame", ["s_b"], ["b01"], {r: H}, "S2 frame bị legal hold -> giữ", hold="LH-S2")
add("b03", "face_crop", ["s_b"], ["b02"], {r: D}, "S2 con của artefact bị hold: xóa (giả định hold_scope=self)")
add("b04", "embedding", ["s_b"], ["b03"], {r: D}, "S2 embedding")

# S3 — danh tính chưa xác minh: escalate TẤT CẢ, kể cả artefact có hold (luật 0 đứng trước hold)
r = req("R-S3", "s_c", verified=False)
add("c01", "raw_video", ["s_c"], [], {r: E}, "S3 chưa xác minh danh tính")
add("c02", "frame", ["s_c"], ["c01"], {r: E}, "S3 có hold nhưng chưa xác minh danh tính -> escalate trước", hold="LH-S3")
add("c03", "face_crop", ["s_c"], ["c02"], {r: E}, "S3 chưa xác minh danh tính")

# S4 — frame chung d,e,f: d và e yêu cầu, f không -> escalate; frame chung d,e (cả hai yêu cầu) -> delete
rd = req("R-S4", "s_d")
re_ = req("R-S5", "s_e")
add("d00", "raw_video", ["s_d"], [], {rd: D}, "S4 raw của d")
add("e00", "raw_video", ["s_e"], [], {re_: D}, "S4 raw của e")
add("de01", "frame", ["s_d", "s_e"], ["d00"], {rd: D, re_: D}, "S4 chung d,e; cả hai đều yêu cầu -> xóa")
add("d01", "frame", ["s_d", "s_e", "s_f"], ["d00"], {rd: E, re_: E}, "S4 chung d,e,f; f không yêu cầu -> escalate")

# S5 — backup thuộc quyền vendor khác
r = req("R-S6", "s_g")
add("g01", "raw_video", ["s_g"], [], {r: D}, "S5 raw")
add("g02", "backup", ["s_g"], ["g01"], {r: E}, "S5 acl=vendor-y, data-platform không có quyền", acl=["vendor-y"])
add("g03", "frame", ["s_g"], ["g01"], {r: D}, "S5 frame")

# S6 — embedding không rõ nguồn gốc
r = req("R-S7", "s_h")
add("h01", "raw_video", ["s_h"], [], {r: D}, "S6 raw")
add("h02", "frame", ["s_h"], ["h01"], {r: D}, "S6 frame")
add("h03", "face_crop", ["s_h"], ["h02"], {r: D}, "S6 face_crop origin biết")
add("h04", "embedding", ["s_h"], ["h03"], {r: E}, "S6 origin_known=false", origin=False)

# S7 — hold + acl vendor trên cùng artefact: legal hold thắng
r = req("R-S8", "s_i")
add("i01", "raw_video", ["s_i"], [], {r: D}, "S7 raw")
add("i02", "frame", ["s_i"], ["i01"], {r: H}, "S7 vừa hold vừa acl vendor -> legal hold ưu tiên hơn acl", hold="LH-S7", acl=["vendor-y"])

# S8 — hold + origin lạ trên artefact cha; con có origin lạ nhưng không hold
r = req("R-S9", "s_j")
add("j01", "raw_video", ["s_j"], [], {r: D}, "S8 raw")
add("j02", "frame", ["s_j"], ["j01"], {r: H}, "S8 hold + origin lạ -> hold ưu tiên hơn origin", hold="LH-S8", origin=False)
add("j03", "face_crop", ["s_j"], ["j02"], {r: E}, "S8 con có origin lạ, không hold -> escalate", origin=False)

# S9 — con của artefact chung chỉ chứa dữ liệu của người khác (m): TUYỆT ĐỐI không xóa
r = req("R-S10", "s_k")
add("k01", "raw_video", ["s_k"], [], {r: D}, "S9 raw")
add("k02", "frame", ["s_k", "s_m"], ["k01"], {r: E}, "S9 chung với s_m (không yêu cầu)")
add("k03", "face_crop", ["s_m"], ["k02"], {r: E}, "S9 chỉ chứa s_m, nằm dưới frame chung -> không được xóa")

# S10 — ba người cùng yêu cầu, artefact chung cả ba -> xóa ở cả ba yêu cầu
rn, ro, rp = req("R-S11", "s_n"), req("R-S12", "s_o"), req("R-S13", "s_p")
add("n01", "raw_video", ["s_n"], [], {rn: D}, "S10 raw của n")
add("o01", "raw_video", ["s_o"], [], {ro: D}, "S10 raw của o")
add("p01", "raw_video", ["s_p"], [], {rp: D}, "S10 raw của p")
add("t01", "frame", ["s_n", "s_o", "s_p"], ["n01"], {rn: D, ro: D, rp: D}, "S10 chung 3 người, cả 3 yêu cầu -> xóa")
add("t02", "annotation", ["s_n", "s_o", "s_p"], ["t01"], {rn: D, ro: D, rp: D}, "S10 annotation chung 3 người")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    (OUT / "data_graph.json").write_text(json.dumps({"version": "selfmade-1", "note": "SELF-MADE test data — nothing real", "artefacts": arts}, indent=1), encoding="utf-8")
    (OUT / "requests.json").write_text(json.dumps(requests, indent=1), encoding="utf-8")
    m = build_manifest(OUT, ["data_graph.json", "requests.json"], source="synthetic:tools/make_selfmade_t08.py (self-made by the group)", license="CC0-1.0 (self-made, synthetic)")
    write_manifest(m, OUT / "manifest.csv")
    with open(GOLD, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["request_id", "artefact_id", "expected_action", "why"])
        w.writerows(sorted(gold))
    print(f"artefacts={len(arts)} requests={len(requests)} gold_rows={len(gold)}")


if __name__ == "__main__":
    main()
