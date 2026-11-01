# hpcc/ – chạy PyBatGym trên HPCC Portal (SuperNodeXP)

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
