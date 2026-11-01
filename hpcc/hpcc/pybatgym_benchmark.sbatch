#!/bin/bash
# Chạy benchmark PyBatGym (backend Mock) như một job Slurm.
#   Gửi job:   sbatch hpcc/pybatgym_benchmark.sbatch
#   Theo dõi:  squeue -u $USER      Kết quả: pybatgym_bench_<jobid>.out và ~/pybatgym_runs/bench_<jobid>/
#
# Biến môi trường (tùy chọn): PYBATGYM_REPO, PYBATGYM_VENV, PYBATGYM_OUT, PYBATGYM_WORKLOADS
#SBATCH --job-name=pybatgym-bench
#SBATCH --account=general
#SBATCH --partition=compute
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --output=pybatgym_bench_%j.out
set -euo pipefail

REPO="${PYBATGYM_REPO:-$HOME/PyBatGym}"
VENV="${PYBATGYM_VENV:-$HOME/venvs/pybatgym}"
JOB="${SLURM_JOB_ID:-manual}"
OUT="${PYBATGYM_OUT:-$HOME/pybatgym_runs/bench_${JOB}}"
WORKLOADS="${PYBATGYM_WORKLOADS:-data/workloads/gen_c32_s*.json}"

# shellcheck disable=SC1091
source "$VENV/bin/activate"
export PYTHONPATH="$REPO"   # không cần pip install -e (pyproject yêu cầu Python >= 3.10, node có 3.9)
cd "$REPO"

echo "node=$(hostname)  job=$JOB  python=$(python --version 2>&1)  repo=$REPO"
echo "git commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

python pybatgym/experiments/run_benchmark.py \
    --workloads "$WORKLOADS" \
    --policies fcfs sjf easy random --random-seeds 3 \
    --out "$OUT"

echo "DONE -> $OUT"
