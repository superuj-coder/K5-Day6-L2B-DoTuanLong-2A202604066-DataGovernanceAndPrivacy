"""PoC pipeline for T08 — Retention & Delete Request Simulator.

5 bước của lab contract:
    01 load     đọc data_graph.json + requests.json, kiểm manifest sha256
    02 process  với mỗi yêu cầu xóa: truy lineage -> phân loại từng artefact bằng bộ luật có thứ tự ưu tiên
    03 rank     hàng chờ review = các artefact KHÔNG được xóa thẳng (escalate / legal hold), xếp theo rủi ro
    04 review   áp quyết định của người duyệt (out/review_queue_reviewed.csv) + audit log
    05 decide   GO / HOLD + reason_code + owner; ghi dry-run plan hoặc mock-delete (idempotent)

Output bắt buộc: out/actions.csv (request_id, artefact_id, action).
Các tham số (đặt trong configs/lab.yaml -> params, CHỐT TRƯỚC KHI xem kết quả eval):
    dry_run        true  : chỉ lập kế hoạch (mặc định). false: "xóa" mock, ghi out/deleted_registry.json
    hold_scope     self | descendants : legal hold chỉ áp cho chính artefact (self) hay lan sang bản dẫn xuất
    multi_subject  all_requested | any_other : artefact nhiều chủ thể chỉ xóa khi TẤT CẢ chủ thể đều có yêu cầu xóa
    budget         số dòng tối đa trong review queue
"""
from __future__ import annotations

import json
from collections import defaultdict, deque

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.io import read_json, write_json
from .common.manifest import verify_manifest
from .common.review import apply_overrides, load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track

ACTIONS = {"delete", "retain_legal_hold", "escalate"}

# Mã lý do (reason_code) — mỗi dòng trong actions.csv đều có một mã.
R_DELETE = "DELETE_IN_SCOPE"
R_HOLD = "LEGAL_HOLD"
R_NO_PERMISSION = "NO_PERMISSION_ACL"
R_UNKNOWN_ORIGIN = "UNKNOWN_ORIGIN"
R_MULTI_SUBJECT = "MULTI_SUBJECT_OTHERS_NOT_REQUESTED"
R_ID_UNVERIFIED = "IDENTITY_NOT_VERIFIED"
R_OVERRIDE = "REVIEWER_OVERRIDE"

# Điểm rủi ro để xếp hàng review (cao = người duyệt xem trước)
RISK = {R_ID_UNVERIFIED: 1.0, R_NO_PERMISSION: 0.9, R_UNKNOWN_ORIGIN: 0.85, R_MULTI_SUBJECT: 0.7, R_HOLD: 0.5, R_DELETE: 0.0}

OPERATOR_ROLE = "data-platform"   # vai trò của hệ thống xóa: chỉ được xóa artefact có role này trong acl


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    if ctx.track != "t08":   # file này chỉ cài T08; track khác -> exit code 3 như template gốc
        spec = get_track(ctx.track)
        raise NotImplementedError(f"src/pipeline.py implements only T08; track {spec.track} ({spec.title}) is not implemented")
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    graph = read_json(ctx.input_dir / "data_graph.json")
    requests = read_json(ctx.input_dir / "requests.json")
    arts = {a["artefact_id"]: a for a in graph["artefacts"]}
    if len(arts) != len(graph["artefacts"]):
        raise ValueError("data_graph.json has duplicate artefact_id")
    children: dict[str, list[str]] = defaultdict(list)
    for a in arts.values():
        for p in a.get("parent_ids", []):
            if p not in arts:
                raise ValueError(f"artefact {a['artefact_id']} has unknown parent {p}")
            children[p].append(a["artefact_id"])
    return {"arts": arts, "children": children, "requests": requests}


# ---------------------------------------------------------------- lineage helpers
def descendants(children: dict, roots: list[str]) -> set[str]:
    """BFS xuống tất cả bản dẫn xuất (frame, crop, embedding, annotation, export...)."""
    seen, q = set(), deque(roots)
    while q:
        n = q.popleft()
        for c in children.get(n, []):
            if c not in seen:
                seen.add(c)
                q.append(c)
    return seen


def ancestors(arts: dict, node: str) -> set[str]:
    seen, q = set(), deque(arts[node].get("parent_ids", []))
    while q:
        n = q.popleft()
        if n not in seen:
            seen.add(n)
            q.extend(arts[n].get("parent_ids", []))
    return seen


def lineage_scope(arts: dict, children: dict, subject_id: str) -> list[str]:
    """Artefact trong phạm vi một yêu cầu = gắn nhãn subject đó + mọi bản dẫn xuất của chúng."""
    own = sorted(a for a, v in arts.items() if subject_id in v.get("subject_ids", []))
    return sorted(set(own) | descendants(children, own))


# ---------------------------------------------------------------- 02 process
def classify(arts: dict, art_id: str, req: dict, requested_subjects: set[str], hold_scope: str, multi_subject: str) -> tuple[str, str, str]:
    """Trả về (action, reason_code, reason). THỨ TỰ ƯU TIÊN (đầu tiên khớp thì thắng):
       0. yêu cầu chưa xác minh danh tính  -> escalate
       1. legal hold                       -> retain_legal_hold
       2. không có quyền (acl)             -> escalate
       3. không rõ nguồn gốc (origin)      -> escalate
       4. nhiều chủ thể, có người chưa yêu cầu xóa -> escalate
       5. còn lại                          -> delete
    """
    a = arts[art_id]
    if not req.get("identity_verified", False):
        return "escalate", R_ID_UNVERIFIED, "identity of requester not verified"
    hold = a.get("legal_hold")
    if not hold and hold_scope == "descendants":
        for anc in sorted(ancestors(arts, art_id)):
            if arts[anc].get("legal_hold"):
                hold = arts[anc]["legal_hold"]
                break
    if hold:
        return "retain_legal_hold", R_HOLD, f"legal hold {hold}: retain until hold is released, then delete"
    if OPERATOR_ROLE not in (a.get("acl") or []):
        return "escalate", R_NO_PERMISSION, f"acl={a.get('acl')} does not include {OPERATOR_ROLE}"
    if not a.get("origin_known", True):
        return "escalate", R_UNKNOWN_ORIGIN, "origin unknown: cannot prove this derives from the requesting subject"
    others = set(a.get("subject_ids", [])) - {req["subject_id"]}
    if others:
        blocked = others - requested_subjects if multi_subject == "all_requested" else others
        if blocked:
            return "escalate", R_MULTI_SUBJECT, f"shared with {len(blocked)} subject(s) without a delete request: {sorted(blocked)[:3]}"
    return "delete", R_DELETE, "in lineage of request, no exception"


def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    if ctx.track != "t08":
        spec = get_track(ctx.track)
        raise NotImplementedError(f"src/pipeline.py implements only T08; track {spec.track} ({spec.title}) is not implemented")
    arts, children, requests = data["arts"], data["children"], data["requests"]
    hold_scope = ctx.param("hold_scope", "self")
    multi = ctx.param("multi_subject", "all_requested")
    requested = {r["subject_id"] for r in requests}
    rows = []
    for req in sorted(requests, key=lambda r: r["request_id"]):
        for art_id in lineage_scope(arts, children, req["subject_id"]):
            action, code, why = classify(arts, art_id, req, requested, hold_scope, multi)
            a = arts[art_id]
            rows.append({
                "request_id": req["request_id"], "artefact_id": art_id, "action": action,
                "reason_code": code, "reason": why, "type": a["type"], "uri": a["uri"],
                "subject_id": req["subject_id"], "deadline": req.get("deadline", ""),
                "score": RISK[code],
            })
    df = pd.DataFrame(rows).sort_values(["request_id", "artefact_id"]).reset_index(drop=True)
    for r in df.itertuples(index=False):   # dry-run: ghi kế hoạch vào audit log cho TỪNG hành động
        ctx.audit.log(actor="pipeline", action=f"plan:{r.action}", item_id=r.artefact_id, reason=r.reason_code,
                      request_id=r.request_id, dry_run=bool(ctx.param("dry_run", True)))
    ctx.stats.update({"n_items": len(df), "n_requests": len(requests), "n_actions": len(df),
                      "by_action": df.action.value_counts().to_dict()})
    return df


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Review queue = các dòng KHÔNG phải delete, rủi ro cao xếp trước."""
    exc = scored[scored.action != "delete"].copy()
    exc["item_key"] = exc.request_id + "|" + exc.artefact_id
    exc["evidence"] = exc.uri
    budget = int(ctx.param("budget", 100))
    q = make_review_queue(exc, "item_key", "score", budget, reason_col="reason_code", action_col="action", slice_col="type", evidence_col="evidence")
    write_review_queue(q, ctx.out("review_queue.csv"))
    ctx.stats["review_queue_size"] = len(q)
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Áp quyết định reviewer. Quy ước:
       approve  -> giữ nguyên hành động đề xuất
       edit     -> override_value ∈ {delete, retain_legal_hold, escalate}
       escalate/skip/reject(không có giá trị) -> giữ nguyên
       KHÔNG cho override 'retain_legal_hold' -> 'delete' (legal hold chỉ gỡ ở hệ thống pháp chế, không gỡ bằng CSV)
    """
    final = scored.copy()
    final["item_key"] = final.request_id + "|" + final.artefact_id
    final["reviewed_by"] = ""
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if reviewed_path.exists():
        reviewed = load_review_decisions(reviewed_path)
        ctx.stats["n_reviewed"] = len(reviewed)
        cur = dict(zip(final.item_key, final.action))
        for r in reviewed.itertuples(index=False):
            if r.item_id not in cur:
                raise ValueError(f"reviewed row {r.item_id!r} is not in this run's actions")
            if r.reviewer_decision in {"edit", "reject"} and str(r.override_value).strip():
                val = str(r.override_value).strip().lower()
                if val not in ACTIONS:
                    raise ValueError(f"override_value {val!r} for {r.item_id} not in {sorted(ACTIONS)}")
                if cur[r.item_id] == "retain_legal_hold" and val == "delete":
                    raise ValueError(f"{r.item_id}: cannot override a legal hold to delete via review CSV")
            ctx.audit.log(actor=r.reviewer, action=f"review:{r.reviewer_decision}", item_id=r.item_id.split("|")[1],
                          before=cur[r.item_id], after=r.override_value or cur[r.item_id], reason=r.review_note, request_id=r.item_id.split("|")[0])
        reviewed = reviewed.assign(override_value=reviewed.override_value.str.strip().str.lower())
        final = apply_overrides(final, reviewed, "item_key", "action", ctx.audit)
        who = {r.item_id: r.reviewer for r in reviewed.itertuples(index=False)}
        changed = reviewed[reviewed.reviewer_decision.isin(["edit", "reject"]) & (reviewed.override_value != "")].item_id
        final.loc[final.item_key.isin(changed), "reason_code"] = R_OVERRIDE
        final["reviewed_by"] = final.item_key.map(who).fillna("")
    return final


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    """GO = kế hoạch xóa đã sạch ngoại lệ chưa duyệt. HOLD = còn escalate chưa có người duyệt."""
    owner = ctx.config.get("owner", "TODO-owner")
    pending = final[(final.action == "escalate") & (final.reviewed_by == "")]
    m = {"n_actions": len(final), **final.action.value_counts().to_dict(), "pending_escalations": len(pending)}
    ev = [str(ctx.out("actions.csv")), str(ctx.out("audit_log.jsonl"))]
    if len(pending):
        return Decision(status="HOLD", reason_code="ESCALATIONS_PENDING_REVIEW", owner=owner, scope="t08", evidence=ev, metrics=m,
                        reason=f"{len(pending)} escalated artefact(s) still need a human decision; execute only the 'delete' rows after approval")
    return Decision(status="GO", reason_code="PLAN_READY", owner=owner, scope="t08", evidence=ev, metrics=m,
                    reason="all exceptions handled or reviewed; deletion plan can be executed")


def execute(ctx: RunContext, final: pd.DataFrame) -> None:
    """Dry-run: chỉ ghi kế hoạch. dry_run=false: 'xóa' mock — idempotent (chạy lại không xóa lần 2)."""
    plan = final[final.action == "delete"][["request_id", "artefact_id", "uri", "type"]]
    plan.to_csv(ctx.out("dry_run_plan.csv"), index=False)
    if ctx.param("dry_run", True):
        ctx.stats["executed"] = 0
        return
    reg_path = ctx.out("deleted_registry.json")
    done = set(json.loads(reg_path.read_text())) if reg_path.exists() else set()
    new = sorted(set(plan.artefact_id) - done)
    for art in new:
        ctx.audit.log(actor="pipeline", action="mock_delete", item_id=art, reason="executed (mock, nothing real is deleted)")
    write_json(reg_path, sorted(done | set(new)))
    ctx.stats["executed"] = len(new)
    ctx.stats["already_deleted_skipped"] = len(set(plan.artefact_id) & done)


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    cols = spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns and c not in ("score", "item_key")]
    final[cols].to_csv(ctx.out(spec.pred_file), index=False)
    execute(ctx, final)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
