# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)


| Mục | Khai báo của nhóm |
|---|---|
| Track | T08 · Retention & Delete Request Simulator |
| Primary metric (tên đúng như evaluator in ra) | Deletion Completeness |
| Tăng tốt hay giảm tốt? | higher (kèm guardrail: False-delete count = 0, lower) |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | cặp (request_id, artefact_id) |
| Công thức + numerator / denominator | số artefact phải xóa mà pred = delete / tổng artefact GT = delete |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | join theo (request_id, artefact_id); thiếu dòng = chưa xóa; delete ngoài phạm vi GT = false-delete |
| Candidate pool cố định | 212 artefact trong data_graph.json, 10 yêu cầu DR-001..DR-010 |
| Review budget B / K | B = 100 (params.budget); queue = mọi dòng không phải delete |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Không có ngưỡng số; thứ tự luật: chưa xác minh danh tính > legal hold > acl > origin lạ > nhiều chủ thể > delete. Tham số hold_scope=self, multi_subject=all_requested (chốt trước eval) |
| Eval split (không dùng để tune) | hidden eval của giảng viên (gt/ không có trong repo) |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | False-delete (xóa nhầm exception) — mục tiêu 0; miss = artefact phải xóa mà bị giữ/escalate |
| Slices sẽ báo cáo (≥2) | theo expected_action (delete / retain_legal_hold / escalate); theo type artefact (raw, backup, frame, face_crop, embedding, annotation, training_export) |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Wilson CI cho tỉ lệ; N exception nhỏ nên báo từng case |
| Ngày giờ chốt + người chốt | 14/11/2026 3:30pm + Do Tuan Long |

