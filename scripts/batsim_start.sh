#!/bin/sh
# BatSim Docker container entrypoint.
#
# FIRST BOOT (docker-compose up): sleep forever, don't launch BatSim.
# RESTART (by RL adapter):        pybatsim is already bound → launch BatSim.
#
# This prevents a "phantom" BatSim from connecting before pybatsim is ready,
# which causes "A simulation is already running" errors.

# ── Locate BatSim binary ─────────────────────────────────────────────────────
BATSIM_BIN=""
for f in /nix/store/*-batsim-*/bin/batsim; do
    [ -x "$f" ] && BATSIM_BIN="$f" && break
done

if [ -z "$BATSIM_BIN" ]; then
    echo "[batsim_start] ERROR: batsim binary not found in /nix/store!"
    exit 1
fi
echo "[batsim_start] Found batsim at $BATSIM_BIN"

# ── Locate 'sleep' ───────────────────────────────────────────────────────────
SLEEP_BIN=""
for f in /nix/store/*/bin/sleep; do
    [ -f "$f" ] && SLEEP_BIN="$f" && break
done

sleep_fn() {
    if [ -n "$SLEEP_BIN" ]; then
        "$SLEEP_BIN" "$1"
    fi
}

# ── Locate 'mkdir' ───────────────────────────────────────────────────────────
MKDIR_BIN=""
for f in /nix/store/*/bin/mkdir; do
    [ -f "$f" ] && MKDIR_BIN="$f" && break
done
[ -n "$MKDIR_BIN" ] && "$MKDIR_BIN" -p /workspace/data/batsim_out

# ── Marker: skip first boot, only run BatSim on restart ──────────────────────
# Nix-based BatSim image may not have /tmp — create it
[ -n "$MKDIR_BIN" ] && "$MKDIR_BIN" -p /tmp
MARKER="/tmp/.batsim_ready"

if [ ! -f "$MARKER" ]; then
    # FIRST BOOT: pybatsim NOT bound yet. Don't launch BatSim.
    echo "[batsim_start] First boot — standing by (waiting for adapter restart)..."
    : > "$MARKER"
    sleep_fn 86400
    exit 0
fi

# ── RESTART: pybatsim should be bound. Launch BatSim. ────────────────────────
BATSIM_PLATFORM=${BATSIM_PLATFORM:-/workspace/data/platforms/medium_platform.xml}
BATSIM_WORKLOAD=${BATSIM_WORKLOAD:-/workspace/data/workloads/medium_workload.json}
BATSIM_SOCKET=${BATSIM_SOCKET:-tcp://shell:28000}

# ── Ghi đè workload theo từng episode ─────────────────────────────────────────
# run_benchmark.py (backend real) ghi đường dẫn workload vào file này trước mỗi lần restart.
# Dùng builtin `read`/`[ -f ]` vì image Nix có thể không có `cat` trong PATH.
OVERRIDE_FILE="${BATSIM_WORKLOAD_FILE:-/workspace/data/.batsim_workload}"
if [ -f "$OVERRIDE_FILE" ]; then
    OVERRIDE=""
    IFS= read -r OVERRIDE < "$OVERRIDE_FILE"
    if [ -n "$OVERRIDE" ] && [ -f "$OVERRIDE" ]; then
        BATSIM_WORKLOAD="$OVERRIDE"
        echo "[batsim_start] Workload override from $OVERRIDE_FILE"
    else
        echo "[batsim_start] WARNING: override file points to a missing workload: '$OVERRIDE' (using default)"
    fi
fi

echo "[batsim_start] Platform : $BATSIM_PLATFORM"
echo "[batsim_start] Workload : $BATSIM_WORKLOAD"
echo "[batsim_start] Socket   : $BATSIM_SOCKET"

echo "[batsim_start] Waiting 2s for pybatsim ZMQ bind..."
sleep_fn 2

echo "[batsim_start] Launching BatSim..."
"$BATSIM_BIN" \
    -p "$BATSIM_PLATFORM" \
    -w "$BATSIM_WORKLOAD" \
    -e /workspace/data/batsim_out \
    -s "$BATSIM_SOCKET" \
    -v information

EXIT_CODE=$?
echo "[batsim_start] BatSim exited with code $EXIT_CODE"

# Keep container alive for next restart
sleep_fn 86400
