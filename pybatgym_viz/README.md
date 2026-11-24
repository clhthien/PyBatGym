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

Waiting time = start − submit (giây mô phỏng). Cam là trung bình = tổng thời gian chờ / số job; xanh là p95 theo nearest-rank: sắp xếp N thời gian chờ rồi lấy phần tử thứ ceil(0,95 × N). Với 100 job, đây là giá trị thứ 95, ít nhất 95 job chờ không quá ngưỡng đó. p95 không phải giá trị lớn nhất; cũng không luôn lớn hơn trung bình nếu có ngoại lệ rất lớn. Hai thanh được vẽ riêng, có nhãn và số cụ thể.

Đồng hồ mô phỏng và thời gian máy tính chạy là hai đồng hồ khác nhau. 4.817,8 giây mô phỏng là khoảng 1 giờ 20 phút trong hệ thống giả lập; simulator có thể tính xong trong vài giây thực vì nhảy từ sự kiện này sang sự kiện khác, không chờ hết thời gian job. Không đổi số đó thành ms. Makespan hiện là đồng hồ kết thúc tính từ gốc episode (bao gồm khoảng trống trước job đầu), throughput là job/giây mô phỏng. Timeout, tuổi snapshot và elapsed là giây thực. Log mới ghi s_sim/s_wall; results/units.json và units.json mô tả đơn vị các trường CSV, giữ nguyên schema và số liệu lịch sử.

Replay tổng hợp event submit/start/finish. Biểu đồ dài lấy mẫu khoảng 900 điểm, giữ đỉnh queue/busy theo bucket; KPI con trỏ dùng event gốc. Timeline mặc định xem toàn episode. Có thể chọn chi tiết quanh con trỏ; nếu có quá nhiều thanh, chế độ toàn episode tổng hợp tỷ lệ bận trong các ô thời gian (tối đa 2.500 ô), không bỏ các core ở đầu lịch sử. Ô tổng hợp không phải job và tooltip ghi rõ tỷ lệ bận. Dữ liệu thiếu native allocation không được dựng giả. Live chỉ là snapshot hiện tại, không phải lịch sử. API job phân trang, cache tối đa 4 run. Live đọc 2 MiB gần nhất của progress.jsonl; run dài có thể thiếu đầu series Live, Replay cuối vẫn dùng jobs.csv.

Ví dụ run 20261124T025647-c71d1571a2ec: FCFS từng sử dụng cả 32 core. Giao diện cũ mặc định nhìn đoạn cuối 4.721,465–4.817,821 giây mô phỏng, khi chỉ còn c17/c18 hoạt động. Đây là giới hạn cửa sổ hiển thị, không phải 30 core chưa từng được cấp job.

Snapshot >8 giây được đánh dấu chậm cập nhật. Run kết thúc thì CPU/RAM là mẫu cuối có timestamp. Chưa có health probe từng dịch vụ; đã bỏ panel pipeline suy trạng thái để tránh hiểu nhầm.

## Chi tiết run — log và dữ liệu

ID, backend/policy, thời điểm tạo, trạng thái/lỗi; metrics và verification; stdout/stderr (64 KiB cuối, tải file để xem đủ); download config/status/verification/CSV theo allowlist. Không public secret/runtime metadata. Trang này phục vụ tìm lỗi/đối chiếu; Dashboard không lặp log.

Trang summary/episodes/TensorBoard comparison cũ đã bỏ. Bookmark /episodes và /comparison chuyển về Playground. Thư viện đọc CSV/TensorBoard giữ cho nghiên cứu; TensorBoard độc lập xem [training](../TRAINING.md).

## Mã và phạm vi

app.py/playground.py: routes; dashboard_data.py: event sweep/cache/pagination; views/playground/: ba trang/layout; public/: CSS/JS local. passenger_wsgi.py/manifest.yml/bin/python: cấu trúc Passenger; serve_local.py mô phỏng SCRIPT_NAME. Worker ghi telemetry, lỗi ghi không thay đổi scheduling.

API cùng run store, kiểm tra ID/path/symlink. Chỉ local loopback/Passenger per-user, chưa phải ứng dụng public hoặc triển khai HPCC thật.
