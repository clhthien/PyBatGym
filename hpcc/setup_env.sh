#!/bin/bash
# Tạo môi trường Python cho PyBatGym trong $HOME (chạy MỘT LẦN trên login node).
# Việc cài môi trường được phép trên login node; việc tính toán phải qua Slurm.
#
#   bash hpcc/setup_env.sh            # đủ để chạy benchmark (Mock): numpy, pydantic, pyyaml, gymnasium
#   bash hpcc/setup_env.sh --with-rl  # thêm PyTorch (CPU), stable-baselines3, sb3-contrib, tensorboard
set -euo pipefail

VENV="${PYBATGYM_VENV:-$HOME/venvs/pybatgym}"

echo "[setup] python hệ thống: $(python3 --version 2>&1) tại $(command -v python3)"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
pip install numpy pydantic pyyaml gymnasium

if [ "${1:-}" = "--with-rl" ]; then
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install stable-baselines3 sb3-contrib tensorboard
fi

python - <<'PY'
import sys
import numpy, pydantic, yaml, gymnasium
print("[setup] OK  python", sys.version.split()[0],
      "| numpy", numpy.__version__, "| pydantic", pydantic.VERSION,
      "| gymnasium", gymnasium.__version__)
PY
echo "[setup] venv: $VENV  (dung luong: $(du -sh "$VENV" | cut -f1))"
