#!/bin/bash
# Script cho launcher của OOD Project Manager (Jobs > Project Manager).
# Form của launcher truyền tham số qua biến môi trường PBG_*; không điền thì dùng giá trị mặc định.
#
#   PBG_POLICIES      các policy, cách nhau bởi dấu cách      (mặc định: fcfs sjf easy random)
#   PBG_WORKLOADS     file hoặc glob workload, tính từ gốc repo (mặc định: data/workloads/gen_c32_s*.json)
#   PBG_RANDOM_SEEDS  số seed cho policy random                (mặc định: 3)
#   PBG_TAG           nhãn của lần chạy                         (mặc định: run)
#   PBG_REPO / PBG_VENV / PBG_OUT_ROOT  đường dẫn repo, venv, thư mục kết quả
#
# Kết quả: $PBG_OUT_ROOT/<thời gian>_<tag>_job<id>/{job.log, results/*}  và liên kết $PBG_OUT_ROOT/latest
#SBATCH --job-name=pybatgym
#SBATCH --account=general
#SBATCH --partition=compute
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00
set -euo pipefail

REPO="${PBG_REPO:-$HOME/PyBatGym}"
VENV="${PBG_VENV:-$HOME/venvs/pybatgym}"
OUT_ROOT="${PBG_OUT_ROOT:-$HOME/pybatgym_runs}"
POLICIES="${PBG_POLICIES:-fcfs sjf easy random}"
WORKLOADS="${PBG_WORKLOADS:-data/workloads/gen_c32_s*.json}"
RANDOM_SEEDS="${PBG_RANDOM_SEEDS:-3}"
TAG="${PBG_TAG:-run}"

# Kiểm tra giá trị đầu vào (chúng đến từ form)
[[ "$POLICIES" =~ ^[a-z_[:space:]]+$ ]]                    || { echo "PBG_POLICIES không hợp lệ: '$POLICIES'" >&2; exit 2; }
[[ "$WORKLOADS" =~ ^[A-Za-z0-9_./*?[:space:]-]+$ ]]        || { echo "PBG_WORKLOADS không hợp lệ: '$WORKLOADS'" >&2; exit 2; }
[[ "$RANDOM_SEEDS" =~ ^[0-9]+$ ]]                          || { echo "PBG_RANDOM_SEEDS phải là số: '$RANDOM_SEEDS'" >&2; exit 2; }
[[ "$TAG" =~ ^[A-Za-z0-9_-]+$ ]]                           || { echo "PBG_TAG chỉ gồm chữ, số, '-' và '_': '$TAG'" >&2; exit 2; }

STAMP="$(date +%Y%m%d-%H%M%S)"
RUN="$OUT_ROOT/${STAMP}_${TAG}_job${SLURM_JOB_ID:-local}"
mkdir -p "$RUN"
exec > >(tee -a "$RUN/job.log") 2>&1

echo "== PyBatGym launcher =="
echo "node=$(hostname)  job=${SLURM_JOB_ID:-local}  start=$(date '+%F %T')"
echo "policies='$POLICIES'  workloads='$WORKLOADS'  random_seeds=$RANDOM_SEEDS  tag=$TAG"
echo "repo=$REPO  venv=$VENV"
echo "run dir: $RUN"

[ -d "$REPO" ]            || { echo "Không thấy repo: $REPO (chạy git clone trước)" >&2; exit 3; }
[ -f "$VENV/bin/activate" ] || { echo "Không thấy venv: $VENV (chạy hpcc/setup_env.sh trước)" >&2; exit 3; }

# shellcheck disable=SC1091
source "$VENV/bin/activate"
export PYTHONPATH="$REPO"
cd "$REPO"
echo "python=$(python --version 2>&1)  git=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

read -r -a POL_ARR <<< "$POLICIES"
read -r -a WL_ARR  <<< "$WORKLOADS"

python pybatgym/experiments/run_benchmark.py \
    --workloads "${WL_ARR[@]}" \
    --policies "${POL_ARR[@]}" \
    --random-seeds "$RANDOM_SEEDS" \
    --out "$RUN/results"

cp -f "$RUN/results/comparison_table.csv" "$RUN/comparison_table.csv" 2>/dev/null || true
ln -sfn "$RUN" "$OUT_ROOT/latest"
echo "== XONG: $RUN  (liên kết nhanh: $OUT_ROOT/latest) =="
