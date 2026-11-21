# Hướng dẫn đọc giao diện

Lệnh chạy/demo: [RUNNER.md](../RUNNER.md). Địa chỉ chính: http://localhost:5050/. Chỉ còn ba trang cần dùng.

## Playground — cấu hình và lịch sử

| Trường | Ý nghĩa |
| --- | --- |
| Workload | File job: thời điểm đến, core, walltime, runtime profile |
| Preset | Core và giới hạn mô phỏng; bài lớn chọn đúng preset trong RUNNER.md |
| Mock / BatSim | Thử nhanh / simulator thật với native CSV được kiểm chứng |
| FCFS | Xét job đến trước; chưa đủ core cho job đầu thì chờ |
| SJF | Trong top-K, chọn job vừa core có walltime ngắn nhất; không biết runtime tương lai |
| EASY | Backfilling theo ước lượng walltime/tài nguyên |
| Random | Chọn action hợp lệ; số seed chỉ hiện khi chọn Random |
| Seed | Nguồn ngẫu nhiên để tái lập; mỗi policy/seed là một episode |
| Timeout | Giới hạn thời gian thực của worker |
| Lịch sử | 50 run; ID mở Chi tiết, Dashboard mở visualization |

Launch tạo ID mới, không ghi đè. Đóng tab không dừng runner. Web chưa Launch training; chế độ Slurm đã kiểm chứng handler trên HPCC, chưa cài UI thành app OOD.

## Dashboard — Live / Replay

| Panel | Cách đọc |
| --- | --- |
| Episode | Một policy + seed. Auto theo lượt đang chạy, hoặc chọn lượt đã có dữ liệu |
| Live / Replay | Snapshot đo khoảng 1 giây, UI cập nhật khoảng 2 giây / phát lại dữ liệu đã lưu |
| PASS / kết quả tạm | PASS cần SUCCEEDED và verification PASS; chưa PASS thì chưa nghiệm thu |
| Hoàn tất / tổng | Job của episode đang xem |
| Tổng toàn run | Cộng mọi episode: 10.000 job × FCFS/SJF = 20.000 job-policy |
| Job chờ / chạy | Đã submit chưa start / đang thực thi |
| Core bận | Core mô phỏng, ví dụ 16/32, không phải CPU thật |
| Đồng hồ mô phỏng | Thời điểm bài toán, thay đổi theo con trỏ Replay |
| Thời gian thực | Từ RUNNING tới hiện tại/finished, gồm kiểm chứng/cleanup |
| Worker CPU/RAM | Tiến trình Python ở run mới. CPU theo một core, RAM VmRSS; không phải toàn máy/BatSim container. Thiếu dữ liệu thì ẩn |
| Replay controls | Phát/tạm dừng, tốc độ, kéo thời gian; tốc độ là bước trên toàn episode |
| Queue & running | Job chờ/chạy theo thời gian mô phỏng |
| Core utilization | % core bận theo thời gian, khác trung bình cả episode |
| Job hoàn tất | Completed cộng dồn |
| So sánh policy | Waiting time trung bình/p95, utilization, makespan, BSD, kèm seed |
| Allocation | Live: core đang cấp cho job từ adapter. Replay: lịch sử native CSV; hover xem job/thời gian |
| Job explorer | Tìm ID, 25 dòng/trang; timestamp tính bằng giây mô phỏng |
| Cách đọc dashboard | Giải thích ngay trong UI, mở khi cần |

Waiting time = start − submit. p95: 95% job chờ không vượt giá trị này. Makespan: thời gian tới khi episode hoàn tất. Bounded slowdown: mức chậm so với runtime với ngưỡng bảo vệ job ngắn. Waiting/slowdown/makespan thấp hơn thường tốt hơn; cần xem workload và các chỉ số còn lại.

Replay tổng hợp event submit/start/finish. Biểu đồ dài lấy mẫu khoảng 900 điểm, giữ đỉnh queue/busy theo bucket; KPI con trỏ dùng event gốc. Timeline tự thu cửa sổ, tối đa 2.500 đoạn; không dựng allocation giả khi thiếu dữ liệu. API job phân trang, cache tối đa 4 run. Live đọc 2 MiB gần nhất của progress.jsonl; run dài có thể thiếu đầu series Live, Replay cuối vẫn dùng jobs.csv.

Snapshot >8 giây được đánh dấu chậm cập nhật. Run kết thúc thì CPU/RAM là mẫu cuối có timestamp. Chưa có health probe từng dịch vụ; đã bỏ panel pipeline suy trạng thái để tránh hiểu nhầm.

## Chi tiết run — log và dữ liệu

ID, backend/policy, thời điểm tạo, trạng thái/lỗi; metrics và verification; stdout/stderr (64 KiB cuối, tải file để xem đủ); download config/status/verification/CSV theo allowlist. Không public secret/runtime metadata. Trang này phục vụ tìm lỗi/đối chiếu; Dashboard không lặp log.

Trang summary/episodes/TensorBoard comparison cũ đã bỏ. Bookmark /episodes và /comparison chuyển về Playground. Thư viện đọc CSV/TensorBoard giữ cho nghiên cứu; TensorBoard độc lập xem [training](../TRAINING.md).

## Mã và phạm vi

app.py/playground.py: routes; dashboard_data.py: event sweep/cache/pagination; views/playground/: ba trang/layout; public/: CSS/JS local. passenger_wsgi.py/manifest.yml/bin/python: cấu trúc Passenger; serve_local.py mô phỏng SCRIPT_NAME. Worker ghi telemetry, lỗi ghi không thay đổi scheduling.

API cùng run store, kiểm tra ID/path/symlink. Chỉ local loopback/Passenger per-user, chưa phải ứng dụng public hoặc triển khai HPCC thật.
