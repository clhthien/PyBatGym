# Runner trên HPCC

## Luồng chạy

Form Flask → kiểm tra cấu hình → tạo thư mục run → `sbatch` → compute node chạy
runner bằng Python 3.10 → Podman chạy BatSim → PyBatGym chạy policy → kiểm chứng
CSV với dữ liệu BatSim → lưu trạng thái, log và kết quả về home NFS.

Web chỉ gửi job và đọc file. Không chạy benchmark trên login node.
Slurm `COMPLETED` chưa đủ để coi thí nghiệm thành công: runner phải có
`SUCCEEDED` và `verification.json` phải là `PASS`.

## Cấu hình và chạy tay

Chạy trong shell HPCC, tại thư mục source mới có `pybatgym/runner/slurm.py`:

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD"
export PYBATGYM_PYTHON="$HOME/venvs/pybatgym310/bin/python"
export PYBATGYM_EXECUTION_MODE=slurm
export PYBATGYM_RUNS_DIR="$HOME/pybatgym_slurm_runs"
export PYBATGYM_SLURM_ACCOUNT=general
export PYBATGYM_SLURM_PARTITION=compute
export PYBATGYM_SLURM_QOS=normal
export PYBATGYM_SLURM_MEMORY=4G
export PYBATGYM_SLURM_TIME=00:15:00

"$PYBATGYM_PYTHON" -m pybatgym.runner.slurm_submit \
  --config configs/playground/real.json \
  --output-root "$PYBATGYM_RUNS_DIR"
```

Lệnh trả về `run_id`, `directory` và `job_id`. Thay các giá trị tương ứng:

```bash
squeue -j JOB_ID
sacct -j JOB_ID --format=JobID,State,ExitCode,Elapsed,NodeList
cat RUN_DIRECTORY/status.json
cat RUN_DIRECTORY/verification.json
cat RUN_DIRECTORY/results/per_episode_metrics.csv
tail -n 40 RUN_DIRECTORY/stderr.log
```

Thư mục còn chứa `results/jobs.csv`, `results/steps.csv`, `slurm_JOB_ID.out/.err`,
`runtime.json`, `podman-pull.log` và dữ liệu BatSim trong `simulator/`.
Mỗi lần chạy tạo thư mục mới.

## Runtime Podman

- Chỉ khởi tạo trong Slurm allocation có `SLURM_JOB_ID`.
- Mỗi run có graphroot, runroot và runtime riêng trong `/tmp/pbg-*` trên compute node.
- Dùng image `docker.io/oarteam/batsim:3.1.0`, lưu image ID và digest thực tế.
- Source được bind chỉ đọc; output container ghi vào scratch rồi sao chép về home.
- Dùng cấu hình cgroupfs/events file riêng, không sửa cấu hình hệ thống.
- Chỉ điều khiển container có nhãn sở hữu và run ID tương ứng. Không prune/xóa
  container hoặc storage khác. Scratch được giữ lại; cần theo dõi dung lượng nếu
  chạy nhiều thí nghiệm. Phiên bản đầu pull image riêng mỗi run nên có chi phí tải.
- `PYBATGYM_SLURM_NODE=node13` chỉ dùng để lặp lại kiểm chứng trên node đã thử;
  không cần đặt biến này khi để scheduler tự chọn node. Các node khác cần được thử thêm.

## Giao diện và giới hạn xác nhận

Ứng dụng Flask dùng cùng biến môi trường trên để Launch qua Slurm. Trang run
hiển thị job ID, trạng thái scheduler, log và kết quả. Polling trạng thái/dashboard
đối chiếu `sacct` để nhận biết job bị scheduler kết thúc khi runner chưa kịp ghi kết quả.

Kiểm chứng handler Flask bằng test client trên HPC không có nghĩa đã cài plugin
trong menu OOD. Cần quản trị cấp Sandbox/gateway hoặc triển khai system app trước
khi mở UI qua portal. Chưa xác nhận huấn luyện PPO hoặc workload lớn trên HPC.

## Bằng chứng thực tế ngày 21/11/2026

Job **8158**, node **node13**, `COMPLETED`, exit `0:0`, 53 giây.
Run: `20261120T173148-37815f024d25` trong `~/pybatgym_slurm_runs/`.
Source thử nghiệm riêng: `~/PyBatGym-slurm-20261121.JYobbMlc`.
Ngày trong run ID dùng UTC nên vẫn là 20/11.

Backend Real, workload `gen_c32_s0`, FCFS và SJF: mỗi policy hoàn tất 100 job;
`verification.json`: **PASS**, tổng 200 dòng job. Sai số thời gian tối đa so với
BatSim native: FCFS 0.000370 giây, SJF 0.000340 giây.

Bản archive đã chạy có SHA256:
`552fe6d246fe7f935d1ceff62b2ded503665746ab3ad57a7fb2a6abc0c8eb093`.
Source local sau đó bổ sung CLI submit, giữ stderr Podman trong log và reconcile
khi dashboard polling; các phần bổ sung này cần được đồng bộ khi triển khai lại.

Job **8159** được gửi từ handler POST của form Flask bằng test client trên HPC:
`20261120T173326-53ab294c6f22`. Kết quả `SUCCEEDED`, scheduler `COMPLETED`,
exit `0:0`, verification `PASS` với cùng 200 dòng job và sai số như job 8158.
GET trang run, dashboard, dashboard/data và tải `results/jobs.csv`,
`results/steps.csv`, `results/per_episode_metrics.csv` đều HTTP **200**.
Đây là kiểm chứng backend/route thật qua Slurm, chưa kiểm chứng giao diện OOD
trong trình duyệt. Script tái kiểm tra ở workspace HPC: `ui_slurm_check.py`.

Kiểm thử local: 66 test runner/UI/Slurm đạt; sau khi thêm test giữ stderr Podman,
9 test trong `tests/test_slurm_runtime.py` đạt (tổng 67 trường hợp đã chạy đạt).
Bằng chứng ảnh: `test-results/hpc-deploy/slurm-8159-proof.jpg`.
