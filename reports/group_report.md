# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> **Lưu ý quan trọng về cách đánh giá:** repo của sinh viên không có ground truth của giảng viên. Toàn bộ số liệu trong báo cáo này
> được chấm bằng **đáp án do nhóm tự gán** (`reports/self_check/`), không phải hidden eval chính thức. Xem mục 02, 05 và 09.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | G01 |
| Challenge | T08 · Retention & Delete Request Simulator |
| Thành viên + vai trò | Đỗ Tuấn Long (thực hiện toàn bộ: thuật toán, test, metric, review, báo cáo) |
| Git URL | https://github.com/superuj-coder/K5-Day6-L2B-DoTuanLong-2A202604066-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | d1cdc429e04f21650c443bd09d3aee81bd132772 |
| Tag `final-24h` (commit) | 4d13a4e4d795dce8bd7c8a97a9252fc35cd97f8f |
| Deadline (giờ VN) | 15/11 |

## 01 · Problem statement

- **Ai bị ảnh hưởng:** chủ thể dữ liệu (người xuất hiện trong video dashcam) gửi yêu cầu xóa. Xóa thiếu thì dữ liệu định danh của họ (frame, face_crop, embedding, backup) vẫn còn. Xóa thừa thì tổ chức mất dữ liệu đang bị legal hold hoặc dữ liệu của người khác, và không khôi phục được.
- **Điểm nghẽn:** dữ liệu của một người nằm rải rác ở nhiều tầng (raw → frame → face_crop → embedding, kèm annotation, backup, training_export). Xóa theo tên file raw bỏ sót bản dẫn xuất; xóa theo lineage mà không xét ngoại lệ thì xóa nhầm.
- **Đầu vào → đầu ra:** `data_graph.json` (212 artefact mock) + `requests.json` (10 yêu cầu DR-001..DR-010) → `out/actions.csv` (`request_id, artefact_id, action ∈ {delete, retain_legal_hold, escalate}`) + `audit_log.jsonl` + `decision.json`.
- **Tiêu chí GO / HOLD / REWORK (chốt trước khi chạy eval):**
  - `GO`: mọi dòng `escalate` đã có người duyệt (cột `reviewed_by` khác rỗng) → kế hoạch xóa được phép thực thi.
  - `HOLD`: còn ít nhất một dòng `escalate` chưa có người duyệt → chỉ thực thi các dòng `delete`, phần còn lại chờ.
  - `REWORK`: không dùng trong T08.
- **Giả định (cần DPO/legal xác nhận):**
  1. Legal hold chỉ áp cho chính artefact bị hold (`hold_scope=self`); bản dẫn xuất vẫn bị xóa. Nhiều tổ chức coi hold lan sang bản dẫn xuất nên cần legal xác nhận.
  2. Artefact dùng chung nhiều chủ thể chỉ xóa khi tất cả chủ thể đều có yêu cầu xóa (`multi_subject=all_requested`).
  3. Training export chứa người chưa yêu cầu xóa không xóa nguyên khối → `escalate` (cần tạo lại export).
  4. Đây là mô phỏng học tập, không phải tư vấn pháp lý; không tuyên bố tuân thủ GDPR hay luật Việt Nam từ kết quả tự động.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev (fixture đề) | 212 artefact, 10 yêu cầu | `fixtures/t08_deletion/` (tạo bởi `tools/make_fixtures.py`, seed 42) | CC0-1.0 | Có (MOCK) |
| eval A: đáp án tự gán trên fixture đề | 52 cặp (request, artefact) | `reports/self_check/gold_t08.csv` | nhóm tự tạo | Có |
| eval B: kịch bản tự tạo | 39 artefact, 13 yêu cầu, 45 cặp đáp án | `fixtures/t08_selfmade/`, `reports/self_check/gold_selfmade.csv` (sinh bởi `tools/make_selfmade_t08.py`) | CC0-1.0 | Có |
| hidden eval của giảng viên | không có trong repo | — | — | — |

- **Ground truth là của nhóm, không phải của giảng viên.** Gold A được gán tay dựa trên dữ kiện của từng artefact (`legal_hold`, `acl`, `origin_known`, `subject_ids`) và thứ tự ưu tiên trong `docs/tracks/T08.md`; mỗi dòng có cột `why`. Gold B được viết cùng lúc với từng artefact khi thiết kế kịch bản. Người gán / người rà soát: **TODO**.
- Schema artefact: `artefact_id, type, subject_ids, parent_ids, uri, owner, acl, legal_hold, origin_known, created_at, filename`. Phân bố fixture đề: frame 45, face_crop 45, embedding 45, annotation 45, raw_video 15, backup 15, training_export 2.
- Ngoại lệ có sẵn trong fixture đề: 2 artefact legal hold (`a0043`, `a0099`), 1 artefact acl `vendor-x` (`a0156`), 3 embedding `origin_known=false` (`a0075`, `a0079`, `a0083`), các artefact nhiều chủ thể, 2 training_export (9–10 chủ thể).
- Seed: 42. Không có train/test split vì bài làm bằng luật, không huấn luyện.
- Manifest sha256: **có**, `python -m tools.verify_manifests` (15 manifest, 0 lỗi); pipeline kiểm lại ở bước `load()` và dừng với exit 2 nếu hash sai.
- Dữ liệu thật: không dùng (đề cấm xóa dữ liệu thật).

## 03 · Research & design

- **Tài liệu tham khảo:** xem mục 11. Ý chính: quyền xóa (GDPR Điều 17(1)) có ngoại lệ khi việc lưu giữ cần thiết để tuân thủ nghĩa vụ pháp lý hoặc để xác lập, thực thi, bào chữa cho yêu cầu pháp lý (Điều 17(3)(b), (e)) → cơ sở để giữ artefact bị legal hold thay vì xóa. Luật BVDLCN 91/2025/QH15 (hiệu lực 01/01/2026) có quyền "yêu cầu cung cấp, xóa, hạn chế xử lý dữ liệu cá nhân" → cơ sở của luồng yêu cầu xóa.
- **Kỹ thuật:** duyệt đồ thị BFS để truy toàn bộ bản dẫn xuất theo từng yêu cầu + bộ luật có thứ tự ưu tiên + người duyệt các ca ngoại lệ. Không dùng machine learning vì bài toán là tuân thủ quy tắc (không phải dự đoán), không có dữ liệu huấn luyện, và xóa nhầm không khôi phục được nên cần hành vi tất định, giải thích được từng dòng bằng `reason_code`.
- **Data flow:**
  ```
  requests.json + data_graph.json
      → 01 load (kiểm manifest sha256)
      → 02 process: BFS lineage từ các artefact gắn subject → classify từng artefact theo luật ưu tiên
      → 03 rank: review queue = mọi dòng KHÔNG phải delete, xếp theo rủi ro
      → 04 review: người duyệt approve/edit (override_value), áp override + audit log
      → 05 decide: GO/HOLD + reason_code + owner; dry-run plan hoặc mock-delete (idempotent)
  ```
- **Luật ưu tiên (khớp luật đầu tiên thì dừng):** chưa xác minh danh tính → legal hold → không có quyền (acl) → không rõ nguồn gốc → nhiều chủ thể còn người chưa yêu cầu → delete. Lý do thứ tự: sai theo hướng "xóa thừa" khó khôi phục hơn "giữ lại chờ duyệt".
- **Thành phần offline:** không dùng model; chỉ Python và pandas.
- **Trade-off:** `escalate` nhiều hơn làm Completeness có thể thấp hơn nhưng False-delete = 0; luật tường minh giải thích được từng dòng nhưng không tự học được ngoại lệ mới.

## 04 · Baseline vs PoC

- **Baseline** (`src/baseline.py`): với mỗi yêu cầu, xóa file raw có tên chứa `subject_id`; không truy lineage, không xét ngoại lệ. Output 10 dòng.
- **PoC** (`src/pipeline.py`, params: `hold_scope=self`, `multi_subject=all_requested`, `dry_run=true`, `budget=100`). Output 164 dòng: 140 delete, 22 escalate, 2 retain_legal_hold.
- Cùng input (`fixtures/t08_deletion`), cùng seed 42, cùng đáp án tự gán (`gold_t08.csv`), cùng cách lọc: **xác nhận**. Commit baseline / PoC: TODO.

**Bảng 1 · Baseline vs PoC** (sinh bởi `python -m src.compare`, file `reports/table1_baseline_vs_poc.md`; đáp án = `gold_t08.csv`, N = 52):

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| Primary: Deletion Completeness (cặp must-delete đã xóa / tổng must-delete) | 0.1389 (5/36) | 1.0000 (36/36) | +0.8611; higher is better |
| Guardrail: False-delete count (xóa nhầm exception + xóa ngoài phạm vi) | 2 | 0 | −2; lower is better, mục tiêu 0 |
| Hard-slice: Exception handling accuracy (legal hold + escalate) | 0.0000 (0/16) | 1.0000 (16/16) | +1.0; baseline = 0 nên không tính % cải thiện; N = 16 |
| Audit trace completeness | 1.0000 (7/7) | 1.0000 (52/52) | 0; cả hai đều đủ dòng audit |
| Runtime / 100 items | 0.0400 s | 0.0148 s | lower is better; CPU x86_64, Python 3.13 (lần chạy tạo file này) |

**Bảng 1b · Bộ kịch bản tự tạo** (`tools.selfcheck_t08`, `reports/self_check/self_check_selfmade_*.json`; N = 45 cặp đáp án):

| Metric | Baseline | PoC | Ghi chú |
|---|---|---|---|
| Deletion Completeness | 0.3871 (12/31) | 1.0000 (31/31) | |
| False-delete count | 1 | 0 | baseline xóa yêu cầu `R-S3` dù chưa xác minh danh tính |
| Exception handling accuracy | 0.0000 (0/14) | 1.0000 (14/14) | 3 legal hold + 11 escalate |
| Audit trace completeness | 1.0000 (13/13) | 1.0000 (45/45) | |

## 05 · Evaluation protocol

- **Primary:** Deletion Completeness = số cặp (request_id, artefact_id) có `expected_action = delete` mà pred cũng `delete` / tổng số cặp có `expected_action = delete`. Dòng gold mà pred không có = chưa xóa.
- **Guardrail:** False-delete count = số exception (hold/escalate) bị pred `delete` + số `delete` ngoài phạm vi gold; mục tiêu 0.
- **Secondary:** Exception handling accuracy; Audit trace completeness (mỗi hành động có một dòng trong `audit_log.jsonl` với `item_id = artefact_id`).
- **Công thức và định nghĩa metric là của evaluator chính thức** (`src/metrics/tracks.py`, không sửa); nhóm chỉ thay đáp án bằng đáp án tự gán (`--gt reports/self_check/gold_t08.csv`).
- **Vì sao phải lọc dự đoán:** gold A chỉ phủ 52 cặp. Evaluator coi mọi dòng `delete` ngoài gold là "xóa nhầm", nên nhóm lọc pred về đúng các cặp có trong gold trước khi chấm (`tools/build_eval_t08.py`). Gold B đầy đủ nên không lọc.
- **Threshold / budget:** không có ngưỡng số. Tham số chính sách chốt trước eval (xem `reports/metric_contract.md`). Review budget B = 100 ≥ 24 dòng ngoại lệ nên không dòng nào bị bỏ ngoài queue.
- **Độ bất định:** N nhỏ, nên báo thêm khoảng Wilson 95%: Completeness PoC 36/36 → [0.904, 1.0], baseline 5/36 → [0.061, 0.287]; Exception handling PoC 16/16 → [0.806, 1.0], baseline 0/16 → [0.0, 0.194]; bộ B Completeness PoC 31/31 → [0.890, 1.0].
- **Lệnh sinh số liệu (một lệnh):** `python -m tools.build_eval_t08`. Lệnh chấm riêng: `python -m src.evaluate --track t08 --gt reports/self_check/gold_t08.csv --pred out/poc/actions_sample.csv --run-name poc --out reports/metrics_poc.json`.

## 06 · Result slices

Slice theo `expected_action` (bộ A, từ `reports/slices_*.csv`):

| Slice | N | Baseline | PoC | Ghi chú |
|---|---|---|---|---|
| delete | 36 | 0.1389 | 1.0000 | baseline chỉ chạm raw (5/36); bỏ sót backup, frame, crop, embedding, annotation |
| escalate | 14 | 0.0000 | 1.0000 | baseline không có khái niệm escalate |
| retain_legal_hold | 2 | 0.0000 | 1.0000 | baseline xóa cả hai raw đang bị hold; N = 2 rất nhỏ (Wilson [0.342, 1.0] với 2/2) |

- **Failure case 1: baseline xóa nhầm legal hold.** Baseline đánh `delete` cho `a0043` (DR-002, hold `LH-2026-03`) và `a0099` (DR-005, hold `LH-2026-07`) vì chọn theo tên file `drive_<subject>_...mp4`, không đọc trường `legal_hold`. PoC giữ cả hai (`retain_legal_hold`, `reason_code=LEGAL_HOLD`).
- **Failure case 2: baseline chỉ xóa raw, giữ bản dẫn xuất.** Với DR-004 (subj_05), baseline chỉ đụng `a0071` (raw). Các frame, face_crop, embedding, annotation, backup cùng chủ thể vẫn còn, trong đó 3 embedding `a0075`, `a0079`, `a0083` còn lưu được định danh. PoC duyệt lineage và chuyển 3 embedding này sang `escalate` vì `origin_known=false`.
- **Failure case 3: baseline xóa khi chưa xác minh danh tính** (bộ B, `R-S3`/`c01`): baseline xóa raw của yêu cầu có `identity_verified=false`; PoC `escalate`.
- **Ca biên của PoC (chưa chắc đúng):** với DR-001, `a0012` và `a0013` chỉ chứa dữ liệu của subj_00 nhưng nằm dưới frame chung `a0011`. PoC đưa vào phạm vi và `escalate` (an toàn vì không xóa). Nếu đáp án của giảng viên coi hai artefact này nằm ngoài phạm vi của yêu cầu thì đó là dòng thừa, không phải lỗi xóa nhầm.
- **Latency / compute:** PoC 0.0148 s / 100 dòng, baseline 0.0400 s / 100 dòng (x86_64, Python 3.13, một lần đo; số chính thức trong `metrics_*.json`).

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` có 24 dòng (22 `escalate` + 2 `retain_legal_hold`), xếp theo rủi ro: danh tính chưa xác minh 1.0 › không có quyền 0.9 › không rõ nguồn gốc 0.85 › nhiều chủ thể 0.7 › legal hold 0.5. B = 100 nên đủ chứa mọi ngoại lệ.
- **Override:** reviewer điền `reviewer`, `reviewer_decision` (`approve` / `edit`), và với `edit` điền thêm `override_value ∈ {delete, retain_legal_hold, escalate}` + `review_note`; lưu thành `out/poc/review_queue_reviewed.csv` rồi chạy lại. Mỗi thay đổi ghi vào `audit_log.jsonl` (ai, lúc nào, trước/sau, lý do).
- **Hai chốt an toàn:** (1) không cho override `retain_legal_hold` → `delete` qua CSV (legal hold chỉ gỡ ở hệ thống pháp chế); (2) dòng có quyết định mà thiếu `reviewer` bị từ chối (exit 2).
- **Decision policy + reason_code + owner:** `ESCALATIONS_PENDING_REVIEW` → HOLD; `PLAN_READY` → GO. Owner: TODO (tên người ký, đã đặt ở `configs/lab.yaml`). Reviewer thực tế: TODO.
- **Khi nào HOLD thay vì tự động thực thi:** còn bất kỳ dòng `escalate` nào chưa có người duyệt. Khi nhóm chỉ có một người, owner và reviewer là cùng một người nên không có kiểm tra chéo (xem mục 09).
- **Bằng chứng reviewer:** TODO. Sau khi duyệt, chép `out/poc/review_queue_reviewed.csv` thành `reports/review_queue.csv` và `out/poc/decision_log.csv` thành `reports/decision_log.csv`.

## 08 · Reproduce & tests

```bash
python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt     # Windows: .\.venv\Scripts\python.exe ...
python -m src.main --track t08 --pipeline src.baseline --output out/baseline --run-name baseline --offline --seed 42
python -m src.main --config configs/lab.yaml --track t08 --output out/poc --run-name poc --offline --seed 42
python -m tools.build_eval_t08      # chấm bằng đáp án tự gán, sinh reports/metrics_*.json và table1
python -m pytest
```

- **Output của `pytest`** (máy dùng để soạn báo cáo): `58 passed, 39 skipped`. 39 test bị bỏ qua là các test cần `gt/` của giảng viên (`requires_gt`). Kết quả trên máy nhóm: TODO.
- **Test của nhóm:** `tests/test_t08.py` (8 test: end-to-end + nhãn gán tay, idempotency, baseline xóa nhầm hold, luồng review + audit, chặn override hold→delete, thiếu reviewer, input bị sửa → exit 2, track khác vẫn exit 3) và `tests/test_t08_selfcheck.py` (PoC khớp đáp án tự gán ở cả hai bộ).
- **Máy / OS / Python:** các file `metrics_*.json` hiện có ghi máy Linux x86_64, Python 3.13.18 (nơi soạn). Chạy lại `python -m tools.build_eval_t08` trên máy nhóm để file ghi đúng máy và git sha. Máy nhóm: TODO · git sha: TODO.

## 09 · Limitations & ethics

- **Đáp án không độc lập.** Gold được gán theo đúng chính sách mà PoC cài đặt, nên PoC đạt 1.0 cho thấy **code thực hiện đúng chính sách**, không chứng minh **chính sách đúng**. Đây là điểm yếu lớn nhất của cách đánh giá này.
- **N nhỏ:** 52 và 45 cặp; slice `retain_legal_hold` chỉ có N = 2 (bộ A) và 3 (bộ B). Con số 100% đi kèm khoảng Wilson rộng, không nên đọc như độ chính xác thật.
- **Chưa kiểm với hidden eval.** Điểm chính thức do giảng viên chấm bằng `gt/` ẩn, có thể khác nếu giảng viên hiểu khác ở hai giả định (`hold_scope`, `multi_subject`) hoặc ở ca biên `a0012`/`a0013`. Đổi hai tham số đó rồi chạy lại `tools.build_eval_t08` để thấy dòng nào đổi nhãn.
- **Rủi ro pháp lý / PII / license:** dữ liệu là mock, không có PII thật. Kết quả chỉ là mô phỏng quy trình, cần DPO/legal xác nhận cách hiểu legal hold, ngoại lệ quyền xóa và xử lý dữ liệu nhiều chủ thể. Không tuyên bố đạt GDPR hay luật Việt Nam.
- **False alarm:** `escalate` có thể nhiều hơn mức cần thiết (ví dụ dùng chung nhưng người kia thực ra đã đồng ý).
- **Một người làm:** owner, reviewer và người gán đáp án có thể là cùng một người nên không có kiểm tra chéo.
- **Scale 10×:** BFS tuyến tính theo số artefact nên vẫn nhanh; điểm nghẽn thật là số dòng `escalate` cần người duyệt.
- **Cải tiến:** nhờ người thứ hai gán lại gold độc lập rồi đo độ lệch; tách xóa từng phần training_export; hẹn xóa khi hết hold; cảnh báo theo `deadline`; resume khi job bị ngắt.

## 10 · Team contribution

**Bảng 2** (đối chiếu `git shortlog -sne --all` và `reports/team_contributions.csv`): TODO điền tên, email git, commit SHA thật.

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| Member 1 | Đỗ Tuấn Long | Toàn bộ: `src/pipeline.py`, `src/baseline.py`, `tests/`, `tools/`, `reports/` | 4d13a4e4d795dce8bd7c8a97a9252fc35cd97f8f | No |
