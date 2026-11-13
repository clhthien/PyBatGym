# Stage 2 — Runner cho Scheduling Playground

Runner nhận JSON, kiểm tra đầu vào, tạo run ID, chạy benchmark trong tiến trình con, lưu trạng thái/log và kiểm chứng output. Đây là CLI cùng Python API dùng cho bước nối UI/OOD sau này; chưa có web server hoặc submit Slurm.

## Chạy bằng Docker sẵn có

Mở PowerShell:

```powershell
cd F:\DACN\Code\DATN\PyBatGym
docker ps --filter label=com.docker.compose.project=pybatgym
```

Shell cần đang chạy. Runner không start/stop Docker Desktop và không build lại image.

Mock:

```powershell
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.runner --config configs/playground/mock.json
```

BatSim thật:

```powershell
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.runner --config configs/playground/real.json
```

Đầu ra cuối cùng:

```json
{"run_id":"...","state":"SUCCEEDED","directory":"/workspace/runs/playground/...","error":null}
```

Mỗi lệnh tạo ID mới, không ghi đè run trước. Trên Windows, `/workspace/runs/playground/<id>` tương ứng `F:\DACN\Code\DATN\PyBatGym\runs\playground\<id>`.

Real yêu cầu image `oarteam/batsim:3.1.0` đã có, pybatsim đã cài, Docker Unix socket được mount và shell thuộc Compose project pybatgym trên network pybatgym_default. Đây là môi trường local đã kiểm chứng, chưa phải runtime Podman/Slurm trên cluster. Không tự pull/build image nếu thiếu.

## Cấu hình công khai

```json
{
  "backend": "real",
  "workload": "gen_c32_s0",
  "policies": ["fcfs", "sjf"],
  "preset": "medium_batsim",
  "seed": 0,
  "random_seeds": 1,
  "timeout_seconds": 120.0
}
```

- `backend`: mock hoặc real.
- `workload`: tên JSON không có đuôi trong data/workloads; không nhận đường dẫn tùy ý, glob hay upload ở Stage 2.
- `preset`: tên YAML trong configs. Với Real, hiện ánh xạ medium_batsim/small_batsim sang XML tương ứng, kiểm tra số compute host trùng cấu hình. Workload nb_res phải trùng platform; ví dụ gen_c32_s0 dùng medium_batsim.
- `policies`: fcfs, sjf, easy, random; không trùng nhau. Chưa hỗ trợ training/PPO model.
- `seed`: seed bắt đầu, được áp dụng vào môi trường và policy. Random chạy random_seeds lần với các seed liên tiếp; các baseline khác chạy một lần theo seed đã chọn.
- `timeout_seconds`: giới hạn thời gian tiến trình benchmark, từ 0.1 đến 86400 giây. Không bao gồm chuẩn bị/validate và thời gian dọn tài nguyên.
- `max_steps`: tùy chọn giới hạn episode, hữu ích khi kiểm thử; episode bị cắt sẽ FAILED, không được tính thành công.

CPU/RAM/walltime của Slurm chưa nằm trong request này. Chúng thuộc lớp submit sau này; không nhầm với số core platform mô phỏng.

Trường lạ bị từ chối. Runner không cho request điều khiển container name, image, network, shell command hay đường dẫn output tùy ý. `--output-root` là tùy chọn CLI cho người triển khai; Real bắt buộc output nằm trong bind mount repo.

## Dữ liệu từng run

```text
runs/playground/<run_id>/
  request.original.json    # nội dung yêu cầu ban đầu
  request.json             # yêu cầu sau validate và điền mặc định
  config_resolved.json     # cấu hình PyBatGym thực dùng
  metadata.json            # UTC, phiên bản, commit, dirty status, hash source/input, exit code
  status.json              # trạng thái, lịch sử, lỗi
  stdout.log
  stderr.log
  verification.json        # chỉ có khi kết quả vượt kiểm tra
  runtime.json             # Real: image ID và runtime context
  results/                 # CSV/config/env benchmark
  simulator/               # Real: output riêng từng episode
    manifest.json
    0/
      resource.json
      container.json
      batsim.log
      batsim_jobs.csv
      batsim_schedule.csv
      batsim_schedule.trace
      batsim_machine_states.csv
```

Input không hợp lệ có thể không tạo request.json/config_resolved.json/results; vẫn có status.json, metadata và log. Thời gian lưu ISO UTC để tránh nhầm timezone giữa portal và compute node.

Trạng thái: CREATED → VALIDATING → RUNNING → VERIFYING → SUCCEEDED. Các nhánh lỗi: FAILED, TIMED_OUT hoặc CANCELLED. Cập nhật status bằng ghi file tạm rồi atomic replace; giao diện tương lai có thể đọc file này cùng log mà không cần parse console để suy ra trạng thái.

Runner chỉ báo SUCCEEDED khi worker exit=0 và kiểm tra đủ episode/job, đúng policy/seed, timestamp hữu hạn, metric nhất quán và đủ artifact. Real kiểm tra thêm exit=0 simulator, sự kiện kết thúc, runtime profile, CSV gốc và sai số timestamp <0.001 giây. Các workload có job timeout/failure trong simulator hiện được xem là kết quả không đạt; cần mở rộng tiêu chí riêng nếu nghiên cứu job failure.

## Theo dõi bằng tay

Trong PowerShell, thay ID thực:

```powershell
Get-Content .\runs\playground\RUN_ID\status.json
Get-Content .\runs\playground\RUN_ID\stdout.log -Tail 30
Get-Content .\runs\playground\RUN_ID\stderr.log -Tail 30
Import-Csv .\runs\playground\RUN_ID\results\comparison_table.csv
```

Lệnh runner chạy đồng bộ; mở terminal khác để xem trạng thái khi job đang chạy. Exit code CLI: 0 thành công, 1 thất bại, 124 timeout, 130 hủy bằng interrupt/SIGTERM. Không suy ra thành công chỉ từ worker exit code.

Python API cho UI/lớp submit sau này:

```python
from pybatgym.runner import run
directory = run({"backend": "mock", "workload": "gen_c32_s0", "policies": ["fcfs"]})
# Hàm đồng bộ; đọc directory/status.json sau khi hoàn tất.
```

API này không tự tạo hàng đợi web. Stage 3 cần khởi chạy runner ngoài request HTTP dài hoặc nhờ OOD/Slurm khởi chạy.

## Tài nguyên và giới hạn

- Real chạy tuần tự trong cùng shell runtime bằng OS lock. Run thứ hai FAILED/REAL_BUSY, không chờ vô hạn; file lock tồn tại không có nghĩa khóa còn giữ, OS tự giải phóng khi tiến trình thoát.
- Mỗi episode có container mới, endpoint riêng và thư mục simulator riêng. Không dùng lại container stage1, không ghi file data/.batsim_workload dùng chung.
- Mã nguồn được mount read-only trong BatSim; chỉ simulator directory của episode được mount writable. Container giới hạn 1 CPU/512 MiB cho smoke benchmark local.
- Cleanup chỉ chọn container có label runner=true và đúng run ID, kiểm tra lại ownership trước khi stop. Không stop/remove container khác, không prune, không reset Docker.
- Container episode đã kết thúc được giữ lại để kiểm tra, không tự xóa; output và container cũ cần chính sách lưu trữ khi triển khai dài hạn.
- Timeout/interrupt dừng process group và container thuộc run, giữ partial log. SIGKILL, mất điện hoặc Docker daemon lỗi có thể ngăn cleanup/status cuối; chưa có dịch vụ recovery cho những trường hợp đó.
- Cần Python >=3.10 như pyproject. Python 3.9 trên HPCC chưa được hỗ trợ/kiểm chứng cho runner mới. Stage này chưa tích hợp Podman hoặc Slurm.

## Kiểm thử

```powershell
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pytest -p no:cacheprovider tests/test_playground_runner.py tests/test_run_benchmark.py tests/test_baselines.py -q
```

Các phép kiểm Docker Real cần image/socket và shared mount nên được kiểm chứng đầu-cuối riêng bằng real.json; bộ pytest không tạo hoặc điều khiển container bên ngoài.
