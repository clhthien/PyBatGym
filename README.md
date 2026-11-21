# PyBatGym Scheduling Playground

Luồng chính: **Web → runner → PyBatGym → Mock/BatSim → kiểm chứng → dashboard và CSV**. Giao diện hiện chạy benchmark baseline; chưa Launch training RL. Adapter Slurm và handler Flask đã chạy BatSim thật trên HPCC, nhưng UI chưa được cài thành app trên portal OOD.

## Tài liệu cần đọc

| File | Nội dung |
| --- | --- |
| [RUNNER.md](RUNNER.md) | **Hướng dẫn chạy chính:** web, CLI, workload, kiểm thử, output, demo GVHD và xử lý lỗi |
| [DEMO.md](DEMO.md) | Kịch bản demo, biểu đồ báo cáo, phạm vi đã đạt và nội dung xin thầy hỗ trợ |
| [Giao diện](pybatgym_viz/README.md) | Ba trang cần dùng và giải thích từng trường/panel/chỉ số |
| [E2E-TEST-CASES.md](E2E-TEST-CASES.md) | 16 kịch bản kiểm thử local |
| [Kết quả benchmark lớn](BENCHMARK-LARGE-RESULTS.md) | Real 1.000/10.000 job ngày 19/11/2026 |
| [Training nâng cao](TRAINING.md) | Script RL/TensorBoard có trong source, tách khỏi benchmark web |
| [HPC](hpcc/README.md) | Script khảo sát cụm và điều kiện tích hợp còn thiếu |

## Mở web trên máy hiện tại

Docker Desktop phải chạy, image PyBatGym/BatSim đã có. PowerShell:

```powershell
cd F:\DACN\Code\DATN\PyBatGym
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml up -d --no-deps --no-build --pull never playground
Start-Process 'http://localhost:5050/'
```

Chọn `gen_c32_s0`, `medium_batsim`, BatSim, FCFS/SJF, seed 0, timeout 120 → Launch → Dashboard. Xem RUNNER.md để kiểm tra image và chạy các chức năng khác.

## Cấu trúc

- `pybatgym/`: environment, adapter, baseline, RL, runner, verification.
- `pybatgym_viz/`: Flask/Passenger preview, form, dashboard, log, download.
- `configs/playground/`: request runner; `configs/*.yaml`: preset mô phỏng.
- `data/workloads/`, `data/platforms/`: đầu vào.
- `runs/playground/<run_id>/`: dữ liệu từng run; `runs/e2e/`: dữ liệu test riêng.
- `tests/`, `pybatgym_viz/test/`: regression; `tests/e2e/`: kiểm thử trình duyệt.

## Phạm vi

Bản đóng gói cố định, không cài dependency lúc startup: xem [release/README.md](release/README.md). Cổng release riêng 5052, không thay bản phát triển 5050.

Local Docker đã kiểm chứng: Mock/Real, FCFS/SJF, Launch nền, trạng thái/log/CSV, Live/Replay và Real đến 10.000 job. Live chỉ có ở run mới ghi telemetry. Dashboard theo phong cách Grafana, không cài Grafana/Prometheus. HPCC: runner qua Podman/Slurm đã PASS 100 job/policy trên node13 (job 8158/8159); chưa triển khai UI trong OOD, chưa nghiệm thu training qua web. Kết quả kiểm thử mới nhất xem DEMO.md.

Không cần khởi động toàn bộ Compose. Không xóa dữ liệu, volume hoặc image để chạy demo.
