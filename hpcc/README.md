# HPCC — runner Slurm và script khảo sát

Luồng HPC cũ/thử nghiệm, không chạy trên Windows. Không dùng script này chứng minh dashboard đã tích hợp Slurm. Runner mới yêu cầu Python >=3.10; workaround PYTHONPATH trên Python 3.9 của Mock cũ không bảo đảm runner mới tương thích. Bản local xem [RUNNER.md](../RUNNER.md).

Cập nhật 21/11/2026: Python 3.10.22 đã kiểm chứng qua job 8151; BatSim smoke đạt ở job 8157; runner mới qua Slurm đạt PASS ở job 8158 với FCFS/SJF, mỗi policy 100 job. Xem [hướng dẫn runner Slurm và bằng chứng](SLURM-RUNNER.md). UI chưa được cài vào menu OOD; cần quyền Sandbox hoặc quản trị triển khai app.

Các script bên dưới thuộc luồng khảo sát cũ, không phải lệnh chạy runner mới.

| File | Chạy ở đâu | Việc |
|---|---|---|
| `setup_env.sh` | login node, một lần | Tạo venv `~/venvs/pybatgym` (numpy, pydantic, pyyaml, gymnasium). `--with-rl` thêm PyTorch CPU + stable-baselines3 |
| `pybatgym_benchmark.sbatch` | `sbatch` trực tiếp | Kiểm tra nhanh môi trường: chạy benchmark Mock đầy đủ như một job Slurm |
| `run_pybatgym.sh` | launcher của Project Manager | Script chạy theo tham số từ form (biến `PBG_*`), ghi kết quả vào `~/pybatgym_runs/` |
| `probe_batsim_podman.sbatch` | `sbatch` trực tiếp | Thử chạy image BatSim bằng podman rootless trên node tính toán |

## Thứ tự
1. Trên cụm: `git clone https://github.com/clhthien/PyBatGym.git ~/PyBatGym`
2. `bash ~/PyBatGym/hpcc/setup_env.sh`
3. `cd ~/PyBatGym && sbatch hpcc/pybatgym_benchmark.sbatch` rồi xem `pybatgym_bench_<jobid>.out`
4. Portal: Jobs > Project Manager > tạo project, thêm launcher dùng `run_pybatgym.sh`
5. Kết quả: `~/pybatgym_runs/latest/` (`job.log`, `comparison_table.csv`, `results/`)

## Lưu ý
- File `.sh` và `.sbatch` phải dùng xuống dòng LF. Nếu gặp lỗi `\r: command not found`: `sed -i 's/\r$//' hpcc/*.sh hpcc/*.sbatch`
- `pyproject.toml` yêu cầu Python >= 3.10 còn cụm có 3.9, nên các script dùng `PYTHONPATH` thay cho `pip install -e .`
- Login node chỉ để cài môi trường, gửi và theo dõi job; việc tính toán chạy qua Slurm.
