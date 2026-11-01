#!/bin/bash
# Phép thử: image BatSim (oarteam/batsim:3.1.0) có chạy được bằng podman rootless trên node tính toán không?
# Tài khoản chưa có dải subuid/subgid nên mặc định podman không giải nén được image. Script thử 2 cách
# (bỏ qua lỗi chown). Mọi dữ liệu nằm ở /tmp của node và bị xóa khi xong.
#   Gửi job:  sbatch hpcc/probe_batsim_podman.sbatch      Kết quả: probe_batsim_<jobid>.out
#SBATCH --job-name=probe-batsim
#SBATCH --account=general
#SBATCH --partition=compute
#SBATCH --qos=normal
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --output=probe_batsim_%j.out
set -u

export XDG_RUNTIME_DIR="/tmp/run-$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
P="/tmp/podman-${USER}-${SLURM_JOB_ID:-$$}"
IMG="docker.io/oarteam/batsim:3.1.0"
OPTS=()

pm() { podman --root "$P/root" --runroot "$P/run" "${OPTS[@]}" "$@"; }

attempt() {
    label="$1"; shift
    OPTS=("$@")
    rm -rf "$P"; mkdir -p "$P/root" "$P/run"
    echo; echo "===== THU: $label ====="
    pm pull "$IMG" 2>&1 | tail -4
    if ! pm image exists "$IMG"; then
        echo "[FAIL] $label: khong pull duoc image"
        return 1
    fi
    echo "[OK] pull xong"
    echo "--- vi tri binary trong image:"
    pm run --rm --entrypoint /bin/sh "$IMG" -c 'ls -d /nix/store/*-batsim-*/bin/batsim' 2>&1 | tail -3
    echo "--- batsim --version:"
    pm run --rm --entrypoint /bin/sh "$IMG" -c 'B=$(ls -d /nix/store/*-batsim-*/bin/batsim | head -1); "$B" --version' 2>&1 | tail -3
    echo "--- dung luong luu tru: $(du -sh "$P" 2>/dev/null | cut -f1)"
    return 0
}

echo "node=$(hostname)  kernel=$(uname -r)  podman=$(podman --version 2>&1)"
echo "== subuid/subgid"
grep "^${USER}:" /etc/subuid /etc/subgid 2>&1 || echo "(khong co dai ID phu)"

attempt "overlay + ignore_chown_errors" --storage-opt overlay.ignore_chown_errors=true \
    || attempt "vfs + ignore_chown_errors" --storage-driver vfs --storage-opt vfs.ignore_chown_errors=true

rm -rf "$P"
echo; echo "PROBE DONE"
