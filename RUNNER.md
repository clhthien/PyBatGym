# Hướng dẫn chạy PyBatGym

Đây là tài liệu chạy chính. Lệnh dùng **PowerShell trên Windows tại repo**, trừ phần ghi rõ trong container/HPC. Giải thích giao diện: [pybatgym_viz/README.md](pybatgym_viz/README.md).

## 1. Chuẩn bị

Nếu muốn chạy bản đóng gói cố định đã kiểm thử, dùng [hướng dẫn release](release/README.md) (cổng 5052). Các lệnh bên dưới dành cho bản development dùng source tại repo (5050).

Mở Docker Desktop bằng tay, đợi engine sẵn sàng. Dùng Python trong image, không cần cài PyBatGym trên Windows để chạy benchmark.

```powershell
cd F:\DACN\Code\DATN\PyBatGym
docker version
docker image inspect ghcr.io/clhthien/pybatgym:latest --format '{{.Id}}'
docker image inspect oarteam/batsim:3.1.0 --format '{{.Id}}'
docker ps --filter label=com.docker.compose.project=pybatgym
```

Hai image inspect phải trả ID. Nếu thiếu, chuẩn bị image đã kiểm chứng trước buổi demo. Lệnh bên dưới không build/pull. Container web mới có thể cần Internet để cài Flask 3.1.3 nếu thiếu. Chỉ chọn service cần chạy; không reset Docker Desktop hoặc xóa dữ liệu để xử lý lỗi.

## 2. Chạy toàn luồng bằng web

```powershell
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml up -d --no-deps --no-build --pull never playground
Start-Process 'http://localhost:5050/'
```

Không cần mở shell, viz, tensorboard hoặc service batsim cũ để dùng web. Runner Real tạo container BatSim riêng cho từng episode.

1. Chọn workload/preset theo bảng dưới, BatSim (hoặc Mock để thử nhanh).
2. Chọn FCFS/SJF, seed 0 và timeout.
3. Launch experiment → Chi tiết: run ID, trạng thái, log.
4. Bấm **Mở dashboard · Live / Replay**. Run mới có Live; kết thúc có Replay.
5. Khi **SUCCEEDED / PASS**, so sánh metrics, tìm job, xem allocation; tải CSV tại Chi tiết.
6. Chạy lại tạo ID mới. Đóng tab không dừng runner. Không restart container có run đang chạy.

| Job/episode | Workload | Preset | Timeout thực | Max steps / max simulation time |
| ---: | --- | --- | ---: | --- |
| 100 | gen_c32_s0 | medium_batsim | 120 s | 5.000 / 50.000 s |
| 1.000 | gen_c32_n1000_s0 | medium_1000_batsim | 600 s | 20.000 / 102.502 s |
| 10.000 | gen_c32_n10000_s0 | medium_10000_batsim | 3.600 s | 200.000 / 1.009.904 s |

Timeout giới hạn worker theo thời gian thực; validation/verification/cleanup có thể làm tổng run lâu hơn. Simulation time là đồng hồ mô phỏng. Các preset trên dùng 32 core mô phỏng. FCFS+SJF với input 10.000 job tạo 20.000 dòng job-policy, không phải input 20.000 job.

Đơn vị: `s_sim` trong log mới = giây mô phỏng; `s_wall` = giây thực. 4.817,8 s mô phỏng không phải 4.817,8 ms: đó là khoảng 1 giờ 20 phút của hệ thống giả lập, có thể tính trong vài giây thực. CSV giữ nguyên đơn vị giây mô phỏng; run mới có `units.json` để đối chiếu. Waiting time = start − submit; cam là trung bình, xanh là p95 (với 100 job, giá trị thứ 95 sau sắp xếp). Timeline mặc định xem toàn episode; chế độ chi tiết chỉ xem quanh con trỏ Replay.

## 3. Chạy bằng terminal

Khởi động riêng shell nếu dùng CLI:

```powershell
docker compose -p pybatgym -f docker-compose.yml up -d --no-deps --no-build --pull never shell
```

Chọn một lệnh, đợi hoàn tất rồi chạy tiếp:

```powershell
# Mock 100 job
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.runner --config configs/playground/mock.json
# Real 100 job
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.runner --config configs/playground/real.json
# Real 1.000 job
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.runner --config configs/playground/real_1000.json
# Real 10.000 job
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.runner --config configs/playground/real_10000.json
```

Mock 1.000/10.000: thay request bằng `configs/playground/mock_1000.json` hoặc `mock_10000.json`. Báo cáo benchmark lớn đã ghi nhận là Real; không suy thành bằng chứng Mock cùng kích thước đã chạy.

CLI trả JSON `run_id`, `state`, `directory`, `error`. Exit code: 0 thành công, 1 lỗi, 124 timeout, 130 hủy. SUCCEEDED chỉ ghi sau kiểm chứng/cleanup; worker exit 0 chưa đủ. Real được khóa tuần tự trong mỗi runtime. CLI shell và UI là hai runtime riêng; tránh chạy đồng thời để demo dễ quan sát.

## 4. Xem output

`/workspace/runs/playground/<id>` tương ứng `F:\DACN\Code\DATN\PyBatGym\runs\playground\<id>`. CLI và web dùng chung output này trong cấu hình local hiện tại.

```powershell
$demoRunId = 'THAY_BANG_RUN_ID'
$demoRunPath = Join-Path (Join-Path (Get-Location) 'runs/playground') $demoRunId
Get-Content (Join-Path $demoRunPath 'status.json')
Get-Content (Join-Path $demoRunPath 'verification.json')
Get-Content (Join-Path $demoRunPath 'stdout.log') -Tail 30
Get-Content (Join-Path $demoRunPath 'stderr.log') -Tail 30
Import-Csv (Join-Path $demoRunPath 'results/comparison_table.csv') | Format-Table -AutoSize
```

| File | Ý nghĩa |
| --- | --- |
| request.json / config_resolved.json | Yêu cầu / cấu hình thực thi |
| status.json | Trạng thái, lịch sử, lỗi |
| verification.json | PASS, số job kiểm tra, sai số native BatSim |
| metadata.json | Phiên bản, commit/hash source/input, exit code |
| stdout.log / stderr.log | Log / lỗi |
| progress.json / progress.jsonl | Snapshot / lịch sử telemetry cho run mới |
| results/comparison_table.csv | So sánh cuối giữa các policy |
| results/jobs.csv / steps.csv | Timestamp job / quyết định scheduling |
| simulator/0/, simulator/1/… | CSV/log/allocation Real từng episode |

Trạng thái: CREATED → QUEUED (web) → VALIDATING → RUNNING → VERIFYING → SUCCEEDED. Nhánh lỗi: FAILED, TIMED_OUT, CANCELLED. Đạt khi SUCCEEDED, verification PASS, đủ job, 0 invalid action; Real còn phải khớp native timestamp <0,001 s và simulator exit 0. Không dùng run FAILED kết luận chất lượng policy. [Kết quả Real 1.000/10.000](BENCHMARK-LARGE-RESULTS.md).

## 5. Kiểm thử

Regression, cần shell chạy:

```powershell
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pytest -p no:cacheprovider tests/test_playground_runner.py tests/test_run_benchmark.py tests/test_baselines.py tests/test_batsim_handshake.py tests/test_docker_log_frames.py tests/test_slurm_runtime.py pybatgym_viz/test -q
```

Không chạy test khóa Real khi benchmark khác còn chạy/cleanup trong cùng shell.

E2E cần Python >=3.10 trên Windows và Chrome:

```powershell
& .\scripts\test_e2e.ps1
# Nếu dependency test đã cài:
& .\scripts\test_e2e.ps1 -SkipInstall
```

Script tạo venv/cache riêng trên ổ repo, mở test service **5051**, output `runs/e2e`, báo cáo `test-results/e2e-<thời gian>`. Workspace demo vẫn ở 5050. Xem [16 test case](E2E-TEST-CASES.md). Đọc kết quả lần chạy mới nhất, không mặc định theo số test cũ.

## 6. Sinh workload

Dùng tên mới để giữ input của run trước. Ví dụ:

```powershell
docker exec pybatgym-shell-1 /opt/venv/bin/python scripts/generate_workload.py --num-jobs 1000 --max-cores 32 --arrival-rate 0.06 --seed 0 --output data/workloads/demo_c32_n1000_s0.json
```

Tăng job không tự tăng giới hạn preset. Runner nhận tối đa 100.000 job; workload thử nghiệm 100.000/1 triệu đã đưa ra thư mục lưu riêng, không nằm trong bản demo. Catalog không đọc file >64 MiB vào web worker. Với bài mới, điều chỉnh preset rồi thử nhỏ trước. SJF hiện chọn trong cửa sổ top-K, không phải toàn hàng đợi.

## 7. Demo GVHD (10–15 phút)

1. Mở Playground: “Người dùng cấu hình thí nghiệm scheduling và Launch từ web.”
2. Chạy Real 100/1.000 job: show ID, trạng thái/log. “Backend nhận yêu cầu; runner điều phối PyBatGym/pybatsim/BatSim.”
3. Dashboard Live: completed, queue, core bận; phân biệt hai đồng hồ và tài nguyên thật/mô phỏng.
4. Khi PASS: Replay, kéo thời gian, xem allocation, chuyển FCFS/SJF, so sánh waiting time/p95/utilization, tải CSV.
5. Mở run 10.000 đã chạy sẵn, nói rõ là kết quả trước đó.
6. Show verification.json và báo cáo E2E. Kết thúc: “Local đã có luồng hoàn chỉnh; runner Slurm đã chạy Real nhỏ trên HPCC. UI trên portal OOD và training qua portal là bước tiếp theo.” Kịch bản và câu trả lời GVHD: [DEMO.md](DEMO.md).

Không cần chạy cả bộ E2E trong buổi gặp. Không gọi prefix OOD local là đã deploy HPCC. Không khẳng định policy luôn tốt hơn từ một workload/seed.

## 8. Lỗi thường gặp và dừng service

| Hiện tượng | Kiểm tra |
| --- | --- |
| Docker engine không kết nối | Mở Docker Desktop, đợi engine; không reset |
| Không mở được 5050 | Log riêng playground, trạng thái service, cổng |
| REAL_BUSY | Đợi run/cleanup kết thúc; không xóa lock |
| Input không khớp | Cùng số core; bài lớn dùng đúng preset trong bảng |
| FAILED / TIMED_OUT | Đọc status, stderr, native logs; không tăng timeout mù quáng |
| Live chưa có/chậm | Run cũ chỉ Replay; xem timestamp snapshot và trạng thái worker |

```powershell
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml logs --tail 50 playground
# Chỉ dừng khi không còn run chạy trong service tương ứng:
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml stop playground
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml stop playground-e2e
```

Không xóa dữ liệu/log/container episode để demo. [Training/TensorBoard](TRAINING.md) là luồng nâng cao riêng; [runner HPC](hpcc/SLURM-RUNNER.md) đã kiểm chứng Slurm/Podman nhưng chưa triển khai UI vào portal.
