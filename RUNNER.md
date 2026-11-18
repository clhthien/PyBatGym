# Stage 2 — Runner cho Scheduling Playground

Runner nhận JSON, kiểm tra đầu vào, tạo run ID, chạy benchmark trong tiến trình con, lưu trạng thái/log và kiểm chứng output. Runner là lõi CLI/Python API; giao diện Stage 3 đã gọi runner để Launch nền. Bản hiện tại chạy local bằng Docker, chưa submit Slurm.

## Hướng dẫn demo và trình bày với GVHD (Stage 1–4 local)

### 1. Mục tiêu buổi demo

Trong khoảng 10–15 phút, chứng minh luồng: **chọn cấu hình → Launch → chạy PyBatGym với BatSim thật → xem trạng thái/log → tải CSV**. Sau đó giải thích runner và đưa bằng chứng kiểm thử. Không cần chạy lần lượt từng stage: thao tác trên UI Stage 3 sẽ gọi runner Stage 2 và lõi Stage 1; Stage 4 kiểm thử lại toàn bộ luồng.

Lời mở đầu gợi ý:

> Em đã xây dựng bản playground local để người dùng cấu hình và chạy thử scheduling policy. Hôm nay em demo FCFS và SJF trên cùng một workload với BatSim thật. Mỗi thí nghiệm có ID, cấu hình, trạng thái, log và kết quả riêng. Đây là bước chuẩn bị tích hợp lên HPC portal; bản demo này chưa gửi job qua Slurm và chưa huấn luyện RL.

### 2. Chuẩn bị trước buổi demo

Mở Docker Desktop bằng tay nếu chưa chạy, chờ Docker sẵn sàng. Mở PowerShell tại Windows và chạy:

```powershell
cd F:\DACN\Code\DATN\PyBatGym
docker ps --filter label=com.docker.compose.project=pybatgym
docker image inspect ghcr.io/clhthien/pybatgym:latest --format '{{.Id}}'
docker image inspect oarteam/batsim:3.1.0 --format '{{.Id}}'
```

Hai lệnh inspect phải trả image ID. Nếu thiếu image hoặc Docker chưa kết nối được, xử lý trước buổi demo; không build/pull image lớn ngay khi trình bày.

Khởi động riêng giao diện playground bằng image sẵn có:

```powershell
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml up -d --no-deps --no-build playground
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml logs --tail 30 playground
Start-Process 'http://localhost:5050/'
```

Lệnh chỉ chọn service `playground`. Không chạy `down`, prune, restart Docker Desktop hoặc thao tác container dự án khác. Không cần khởi động service `batsim` cũ: runner Real tự tạo container BatSim riêng cho mỗi episode. Giao diện mới có thể cần Internet để cài Flask nếu container chưa có dependency này.

Trước buổi gặp, chạy thử Real một lần và giữ một run PASS để dự phòng. Không restart container playground khi thí nghiệm đang chạy. Chuẩn bị sẵn một tab giao diện, một cửa sổ PowerShell và thư mục `runs/playground` trong Explorer.

### 3. Demo chính trên giao diện (khoảng 5 phút)

Tại `http://localhost:5050/`, cấu hình:

| Trường | Giá trị demo | Cách giải thích |
| --- | --- | --- |
| Backend | BatSim / Real | Dùng simulator thật thay cho Mock |
| Workload | `gen_c32_s0` | Bộ đầu vào mẫu gồm 100 job |
| Preset | `medium_batsim` | Platform mô phỏng 32 core, khớp workload |
| Policies | FCFS và SJF | So sánh hai cách chọn job trên cùng dữ liệu |
| Seed | `0` | Ghi lại seed để tái lập cấu hình |
| Timeout | `120` giây | Giới hạn thời gian thực thi benchmark |

Trình tự show và lời trình bày:

1. **Show form trước khi Launch.** “Đây là đầu vào của thí nghiệm. 32 core là tài nguyên trong mô phỏng, không phải em xin 32 CPU thật từ máy hoặc Slurm.”
2. **Nhấn Launch experiment một lần.** Chỉ vào run ID mới. “Backend kiểm tra cấu hình, cấp ID, lưu yêu cầu và khởi chạy runner nền.”
3. **Show trạng thái và log tự cập nhật.** “Runner gọi PyBatGym; adapter trao đổi với BatSim qua pybatsim. FCFS lấy job đến trước, SJF ưu tiên job ngắn.” Một số trạng thái chuyển nhanh nên UI có thể không kịp hiển thị tất cả; sau đó xem lịch sử trong `status.json`.
4. **Chờ Thành công / PASS.** “Runner kiểm tra output sau khi tiến trình kết thúc, rồi mới xác nhận thành công.” Nếu lỗi, show thông báo và log thực tế; không gọi run lỗi là PASS.
5. **Show bảng so sánh FCFS/SJF.** Giải thích thời gian chờ là thời gian từ lúc job đến đến lúc bắt đầu; makespan là thời gian hoàn tất toàn bộ workload. Chỉ kết luận theo số liệu hiện trên màn hình, không khẳng định SJF luôn tốt hơn trên mọi workload.
6. **Bấm Tải CSV và mở file.** “Kết quả có thể tải về để phân tích và đưa vào báo cáo.”
7. **Về trang đầu, chạy lại cùng cấu hình.** Show hai run ID khác nhau và mở lại run đầu. “Chạy lại tạo dữ liệu mới, không ghi đè kết quả cũ.” Chờ run Real đầu kết thúc rồi mới Launch Real tiếp.

Nếu muốn giải thích Mock, chỉ cần nói Mock phục vụ kiểm tra nhanh luồng phần mềm; bằng chứng chính của demo là run BatSim thật. Không thay Real bằng Mock mà vẫn trình bày là simulator thật.

### 4. Show dữ liệu bên dưới và vai trò runner (khoảng 3 phút)

Copy run ID từ trang kết quả, thay chuỗi bên dưới rồi chạy trong PowerShell:

```powershell
$demoRunId = 'THAY_BANG_RUN_ID_TREN_GIAO_DIEN'
$demoRunPath = Join-Path 'F:\DACN\Code\DATN\PyBatGym\runs\playground' $demoRunId
Get-Content (Join-Path $demoRunPath 'request.json')
Get-Content (Join-Path $demoRunPath 'status.json')
Get-Content (Join-Path $demoRunPath 'verification.json')
Import-Csv (Join-Path $demoRunPath 'results\comparison_table.csv') | Format-Table -AutoSize
Get-ChildItem (Join-Path $demoRunPath 'simulator') -Recurse -Filter batsim_jobs.csv
```

Chỉ cần show bốn bằng chứng: cấu hình đã lưu, lịch sử trạng thái, kết quả verification và CSV gốc của BatSim. Khi cần xem lỗi:

```powershell
Get-Content (Join-Path $demoRunPath 'stdout.log') -Tail 30
Get-Content (Join-Path $demoRunPath 'stderr.log') -Tail 30
```

Giải thích kiến trúc bằng một câu:

> Giao diện nhận yêu cầu và hiển thị kết quả; backend kiểm tra yêu cầu và Launch nền; runner quản lý vòng đời lượt chạy; PyBatGym thực thi policy và giao tiếp với BatSim qua adapter pybatsim; kết quả được lưu theo run ID.

Nếu GVHD muốn thấy chạy không qua UI, dùng các lệnh CLI Mock/Real ở phần “Chạy bằng Docker sẵn có” bên dưới. Chỉ chạy khi container shell đang hoạt động, và đợi lượt Real demo trước hoàn tất. Đây là cùng lõi runner, không phải một hệ thống khác.

### 5. Show kiểm thử Stage 4 (khoảng 2 phút)

Trước buổi demo, chạy trong PowerShell tại repo:

```powershell
& .\scripts\test_e2e.ps1
```

Xem báo cáo mới trong `test-results/e2e-<thời gian>`. Test dùng workspace riêng `runs/e2e` và cổng 5051; giao diện demo chính vẫn ở 5050. Xem chi tiết 15 tình huống trong [E2E-TEST-CASES.md](E2E-TEST-CASES.md). Nếu đã cài dependency test, có thể dùng `-SkipInstall`.

Không cần chạy hết bộ test trong lúc trình bày nếu thiếu thời gian. Show báo cáo lần chạy thật gần nhất, kèm ngày chạy; phân biệt với kết quả đã ghi nhận ngày 14/11/2026: **15/15 E2E và 65/65 regression đạt**. Báo cáo mới phải được đọc theo kết quả thực tế, không mặc định vẫn đạt.

Lời trình bày gợi ý:

> Em đã kiểm thử từ trình duyệt tới simulator thật, gồm Launch thành công, tải CSV, input sai, timeout, gửi trùng, không ghi đè run và mở lại tab. E2E chạy tách dữ liệu khỏi buổi demo. Phần kiểm thử này mới xác nhận môi trường local.

### 6. Kết thúc và nêu bước tiếp theo

> Em đã hoàn thành luồng playground local với baseline FCFS/SJF và BatSim thật. Bước tiếp theo là xác nhận môi trường chạy trên compute node, nối backend submit qua Slurm, rồi triển khai ứng dụng vào OOD khi có quyền phù hợp. Sau đó mới mở rộng training RL và dashboard chi tiết.

Không trình bày đường dẫn `/pun/dev/...` của bản preview là bằng chứng đã deploy lên portal. Không dùng job Slurm hello đã chạy trước đây làm bằng chứng PyBatGym đã được tích hợp Slurm. Training PPO, runtime Podman trên HPC và triển khai OOD thật chưa nằm trong kết quả Stage 1–4 local.

### 7. Nếu gặp lỗi lúc demo

| Hiện tượng | Việc cần kiểm tra |
| --- | --- |
| Không mở được 5050 | Xem `docker ps` lọc project và log riêng `playground` bằng lệnh ở trên |
| UI báo cấu hình không khớp | Dùng `gen_c32_s0` với `medium_batsim` |
| `REAL_BUSY` | Đợi run Real đang chạy trong runtime đó kết thúc; không xóa lock hoặc dừng container tùy tiện |
| Timeout hoặc FAILED | Mở log và `status.json`, giải thích lỗi; chỉ chạy lại sau khi xác định nguyên nhân |
| Chưa sửa kịp trong buổi gặp | Show run Real PASS đã chuẩn bị và nói rõ đó là kết quả lần chạy trước |

Chỉ dừng riêng UI sau buổi demo nếu không còn run đang chạy:

```powershell
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml stop playground
```

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

Trạng thái CLI: CREATED → VALIDATING → RUNNING → VERIFYING → SUCCEEDED; Launch từ UI có thêm QUEUED. Các nhánh lỗi: FAILED, TIMED_OUT hoặc CANCELLED. Cập nhật status bằng ghi file tạm rồi atomic replace; giao diện đọc trạng thái cùng log mà không cần parse console để suy ra trạng thái.

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

API này không tự tạo hàng đợi web. Stage 3 đã khởi chạy runner nền ngoài request HTTP dài; lớp submit Slurm vẫn là bước tích hợp tiếp theo.

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
