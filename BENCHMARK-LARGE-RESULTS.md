# Kết quả BatSim 1.000 và 10.000 job — 19/11/2026

Chạy Real bằng runner, policies FCFS/SJF, seed=0, platform 32 core. Các số giây dưới đây là thời gian mô phỏng.

| Job/policy | Run ID | Policy | Waiting time trung bình (s) | Utilization | Makespan (s) |
| --- | --- | --- | ---: | ---: | ---: |
| 1,000 | `20261119T153611-6af22a6ba302` | FCFS | 11,654.058 | 55.78% | 39,280.137 |
| 1,000 | `20261119T153611-6af22a6ba302` | SJF | 8,257.151 | 57.77% | 37,925.748 |

- 1,000 job/policy: SJF giảm waiting time trung bình 29.15% so với FCFS ở workload này. Tổng 2,000 dòng job đã kiểm tra. Sai số native timestamp tối đa 0.000386s. Thời gian thực từ RUNNING đến SUCCEEDED khoảng 238.2s, bao gồm verification/cleanup.

| Job/policy | Run ID | Policy | Waiting time trung bình (s) | Utilization | Makespan (s) |
| --- | --- | --- | ---: | ---: | ---: |
| 10,000 | `20261119T154030-82db4fee7e16` | FCFS | 112,527.244 | 56.03% | 396,788.984 |
| 10,000 | `20261119T154030-82db4fee7e16` | SJF | 100,311.180 | 57.49% | 386,747.703 |

- 10,000 job/policy: SJF giảm waiting time trung bình 10.86% so với FCFS ở workload này. Tổng 20,000 dòng job đã kiểm tra. Sai số native timestamp tối đa 0.000490s. Thời gian thực từ RUNNING đến SUCCEEDED khoảng 1051.3s, bao gồm verification/cleanup.

## Lỗi phát hiện và sửa

- Run 10.000 đầu `20261119T151755-7f7b405da3a9` FAILED vì invalid actions (FCFS 131, SJF 121), dù đủ job. Không dùng kết quả này để kết luận chất lượng policy.
- Adapter phát READY ở onSimulationBegins, trước decision barrier. Reset/step có thể lệch nhịp và action mask không còn cùng trạng thái với quyết định. Bỏ token READY riêng; chỉ nhả agent tại onNoMoreEvents khi scheduler đang đợi action. Đã có test handshake và hai run Real mới PASS.
- Run 1.000 trước sửa `20261119T151658-7546212f1d71` được giữ nguyên nhưng số liệu báo cáo dùng run sau sửa.
- Thu log Docker dùng slicing lặp trên phần còn lại gây chậm với log ~14 MB/episode. Đổi sang duyệt offset; test 20.000 frame giữ nội dung đúng. Lượt 10.000 trên dùng mã cũ đã nạp nên thời gian cleanup chưa phản ánh tối ưu mới.

## Xem kết quả

Mở http://localhost:5050/pun/dev/pybatgym_playground/playground/runs/<run_id> với ID trong bảng. Các artifact nằm dưới runs/playground/<run_id>. Không xóa dữ liệu run cũ.

## Cải tiến giao diện

Dashboard Live/Replay đã có: xem [giải thích giao diện](pybatgym_viz/README.md). Đây là dashboard PyBatGym, không phải Grafana server.

## Kiểm thử mã

Cập nhật 22/11/2026: chạy lại Real 1.000 job/policy bằng source hiện tại đạt
SUCCEEDED/PASS, run `20261121T190121-6f75ce0d836c`, đủ 2.000 dòng job, 0 invalid
action, sai số native tối đa 0.000386 s. Mean wait FCFS/SJF vẫn tương ứng
11654.058294 / 8257.150899 s. Không chạy lại 10.000 trong lượt này.
Biểu đồ PNG/PDF, CSV tổng hợp và nguồn: `demo/20261122/`.
86/86 regression và 16/16 browser E2E đạt sau sửa lỗi đọc log; xem DEMO.md.
Các kết quả kiểm thử bên dưới là lịch sử ngày 19/11.

- 37 test runner/baseline/handshake PASS sau bản sửa đồng bộ.
- Bộ regression mở rộng: 69 PASS, 1 lỗi do test khóa Real chạy khi benchmark còn giữ khóa cleanup. Sau benchmark, chạy lại riêng test đó: PASS (2.41s). Không phải một lượt 70/70 đồng thời.
- Test parser log 20.000 frame và handshake: 2 PASS (2.21s).
- Chưa chạy lại browser E2E trong lượt này; chưa commit/push.
