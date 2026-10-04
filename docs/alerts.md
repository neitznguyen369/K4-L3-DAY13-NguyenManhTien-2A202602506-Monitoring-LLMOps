# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: `fast_successful_requests` (`latency_ms <= 2000`, target 99.5%/28 ngày)
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms) > 2000ms` liên tục trong 5 phút. Baseline P95 của tôi chỉ ~151ms nên ngưỡng 2000ms rất xa mức bình thường; sự cố `rag_slow` đẩy latency lên ~2651ms và vượt ngưỡng này.
- Ảnh hưởng tới người dùng: câu trả lời đến chậm hơn ~2.5 giây so với bình thường, đốt error budget nhanh.
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard panel *Latency percentiles and TTFT* để xác nhận P95/P99 và mốc thời gian bắt đầu tăng. Nếu TTFT P95 vẫn ~50ms trong khi latency tăng thì nghi ngờ bước trước LLM (retrieval).
  2. Chạy `python scripts/find_slow_requests.py --threshold-ms 2000 --since <ISO time>` để lấy `correlation_id` của request chậm.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh span `retrieval` và `llm-generate`; span nào chiếm phần lớn thời gian là nguyên nhân.
- Mitigation tạm thời: tắt incident/practice scenario nếu đang bật (`python scripts/inject_incident.py --scenario rag_slow --disable`), khôi phục dependency retrieval (vector store) hoặc giảm tải; nếu trace cho thấy `llm-generate` chậm sau khi đổi prompt thì rollback label `production` về version cũ.
- Owner: `student-2A202602506`

## Alert 2

- Tên: `HighErrorRateOrRetrievalFailure`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `error_rate_pct_max = 2` và `retrieval_success_rate_pct_min = 90`
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received) * 100 > 2` HOẶC `tool_success` rate < 90% trong 5 phút liên tục.
- Ảnh hưởng tới người dùng: request trả HTTP 500, người dùng không nhận được câu trả lời (ví dụ khi vector store timeout, `tool_fail`).
- Ba bước kiểm tra đầu tiên:
  1. Mở panel *Error rate and retrieval success*, xem `error_type` chiếm đa số và thời điểm bắt đầu.
  2. Lọc `data/logs.jsonl` theo `event == "request_failed"`, lấy `correlation_id`, đọc `error_type`, `tool_name`, `tool_success=false`.
  3. Mở trace cùng `correlation_id`; span `retrieval` có `level=ERROR` và status message cho biết lỗi (ví dụ `RuntimeError: Vector store timeout`).
- Mitigation tạm thời: khôi phục vector store/dependency, tắt scenario `tool_fail` nếu đang chạy thử, hoặc bật câu trả lời fallback không dùng retrieval trong lúc sửa.
- Owner: `student-2A202602506`

## Alert 3

- Tên: `HighCostPerRequest`
- Severity: `warning`
- Duration: `10m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max = 2.5`
- Điều kiện và thời gian duy trì: `avg(response_sent.cost_usd) > 0.004 USD` trên mỗi request trong 10 phút. Baseline khoảng 0.002 USD/request (output ~130 token); `cost_spike` nhân output token lên 4 lần đẩy chi phí lên ~0.008 USD/request.
- Ảnh hưởng tới người dùng: người dùng không chậm hơn nhưng chi phí vận hành tăng gấp nhiều lần, có thể vượt ngân sách ngày.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel *Cost over time* và *Input and output tokens*; so sánh với traffic để biết chi phí tăng do số request hay do token/request.
  2. Lọc `response_sent` có `tokens_out` cao bất thường, lấy `correlation_id`.
  3. Mở trace tương ứng, xem generation `llm-generate` (usage/cost) và `prompt_version` để biết có phải prompt mới làm câu trả lời dài hơn không.
- Mitigation tạm thời: rollback prompt `production` về version trước, giới hạn độ dài đầu ra, hoặc tắt `cost_spike` nếu đang chạy thử.
- Owner: `student-2A202602506`
