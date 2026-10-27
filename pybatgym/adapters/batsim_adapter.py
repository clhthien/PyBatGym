"""Real BatSim adapter connecting PyBatGym to the actual C++ BatSim simulator via pybatsim."""

import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Optional

from .mock_adapter import BatsimAdapter
from pybatgym.core import (
    Event,
    EventType,
    Job,
    JobStatus,
    Resource,
    ScheduleCommand,
    ScheduleCommandType,
)

try:
    from batsim.batsim import BatsimScheduler, Batsim
except ImportError:
    BatsimScheduler = object

    def Batsim(*args, **kwargs):
        raise ImportError(
            "pybatsim is not installed. Run: pip install pybatsim"
        )


# Default paths resolved relative to the project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BATSIM_DATA = _PROJECT_ROOT / "batsim_data"
_DEFAULT_PLATFORM = _BATSIM_DATA / "platforms" / "medium_platform.xml"
_DEFAULT_WORKLOAD = _PROJECT_ROOT / "data" / "workloads" / "medium_workload.json"

# Known BatSim binary locations (searched in order)
_BATSIM_SEARCH_PATHS = [
    _BATSIM_DATA / "result" / "bin" / "batsim",   # Nix build (local)
    Path("/opt/batsim/bin/batsim"),                # Docker image (committed)
    Path("/usr/local/bin/batsim"),                 # System install
    Path("/usr/bin/batsim"),
]


def _find_batsim() -> str:
    """Find batsim binary: check known locations first, then fall back to PATH."""
    import shutil
    # 1. Check known absolute paths
    for p in _BATSIM_SEARCH_PATHS:
        if p.exists() and p.is_file():
            return str(p)
    # 2. Fall back to PATH
    found = shutil.which("batsim")
    if found:
        return found
    raise FileNotFoundError(
        "[RealBatsimAdapter] 'batsim' not found.\n"
        f"  Checked: {[str(p) for p in _BATSIM_SEARCH_PATHS]}\n"
        "  Fix: export PATH=/workspace/batsim_data/result/bin:$PATH"
    )


class RealBatsimAdapter(BatsimAdapter, BatsimScheduler):
    """Integrates real BatSim simulator using pybatsim over ZeroMQ.

    Architecture:
    - Main thread (RL agent) ←→ queues ←→ background thread (pybatsim)
    - Background thread runs BatSim C++ process + pybatsim event loop
    - Queues decouple synchronous RL step() calls from async BatSim callbacks
    """

    def __init__(self, config, socket_endpoint: str = "tcp://*:28000") -> None:
        BatsimScheduler.__init__(self)

        self.config = config
        # pybatsim is the ZMQ SERVER — it BINDs to this address.
        # BatSim binary (batsim container) CONNECTs to tcp://shell:28000.
        # Override via BATSIM_SOCKET env var if needed (e.g. different port).
        self.socket_endpoint = os.environ.get("BATSIM_SOCKET", socket_endpoint)
        self._default_port: int = 28000

        # Threading bridges
        self._action_queue: queue.Queue = queue.Queue()
        self._state_queue: queue.Queue = queue.Queue()
        self._batsim_thread: Optional[threading.Thread] = None
        self._batsim_proc: Optional[subprocess.Popen] = None

        # Simulation state (shared between threads - updated by pybatsim callbacks)
        self._internal_time: float = 0.0
        self._is_done: bool = False
        self._pending_jobs: list[Job] = []
        self._running_jobs: list[Job] = []
        self._completed_jobs: list[Job] = []
        self._events: list[Event] = []
        self._resource: Resource = self._make_resource()
        # Maps our integer job_id → full BatSim job id string (e.g. 0 → "w0!0")
        self._batsim_job_id_map: dict[int, str] = {}
        self._lock = threading.Lock()  # Prevent concurrent resets

    # --------------------------------------------------------------------------
    # BatsimAdapter interface (called from main/RL thread)
    # --------------------------------------------------------------------------

    def start(self) -> None:
        """No-op: actual initialization happens in reset()."""
        pass

    def reset(self) -> tuple[list[Event], Resource]:
        """Restart simulation: clean up previous run, then spawn fresh BatSim.

        Sequence:
        1. Kill old simulation (thread + subprocess)
        2. Clear internal state and drain queues
        3. Start pybatsim thread → BINDs tcp://*:28000 (ZMQ server)
        4. Start/restart BatSim container → CONNECTs to tcp://shell:28000
        5. Wait for SIMULATION_BEGINS from BatSim
        """
        with self._lock:
            self._kill_simulation()
            self._clear_state()

            self._start_pybatsim_thread()       # Step 3: bind ZMQ first
            import time; time.sleep(2)          # ensure ZMQ is bound before BatSim connects
            self._start_batsim_subprocess()     # Step 4: start/restart BatSim container
            
            # Extra wait for Docker container to fully stabilize
            time.sleep(3)
            
            self._wait_for_next_state()
            return self._consume_events(), self._resource

    def step(self, command: Optional[ScheduleCommand]) -> tuple[list[Event], bool]:
        """Send scheduling decision and advance simulation to next decision point."""
        if self._is_done:
            return [], True

        self._action_queue.put([command] if command else [])
        self._wait_for_next_state()
        return self._consume_events(), self._is_done

    def close(self) -> None:
        """Terminate BatSim process and background thread."""
        self._kill_simulation()  # Fix 1: unified cleanup

    def get_current_time(self) -> float:
        return self._internal_time

    def get_pending_jobs(self) -> list[Job]:
        return list(self._pending_jobs)

    def get_completed_jobs(self) -> list[Job]:
        return list(self._completed_jobs)

    def get_resource(self) -> Resource:
        return self._resource

    # --------------------------------------------------------------------------
    # Private helpers
    # --------------------------------------------------------------------------

    def _make_resource(self) -> Resource:
        return Resource(
            total_nodes=self.config.platform.total_nodes,
            total_cores_per_node=self.config.platform.cores_per_node,
        )

    @staticmethod
    def _find_free_port(start: int = 28000) -> int:
        """Find an available TCP port, starting from `start`. (Fix 3)"""
        import socket as _socket
        for port in range(start, start + 100):
            try:
                with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                    s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                    s.bind(('', port))
                    return port
            except OSError:
                continue
        return start  # fallback — caller will handle bind error

    def _kill_simulation(self) -> None:
        """Cleanly stop pybatsim thread and BatSim subprocess.

        Order matters:
        1. Signal thread via _is_done flag + unblock any action_queue.get()
        2. If simulation ended naturally, wait for thread to finish cleanly
           (so BatSim gets the final ACK and can write its output files).
        3. Only force-close ZMQ if simulation did NOT end naturally.
        4. Terminate subprocess if needed.
        5. Join thread.
        6. Force-reset Batsim.running singleton.
        """
        import time

        simulation_ended_naturally = self._is_done

        # Step 1: signal stop
        self._is_done = True
        try:
            self._action_queue.put_nowait([])
        except Exception:
            pass

        if simulation_ended_naturally:
            # Simulation finished via SIMULATION_ENDS → pybatsim thread is
            # already in cleanup. Give it time to send the final ACK so BatSim
            # can write its output files before exiting.
            if self._batsim_thread is not None and self._batsim_thread.is_alive():
                self._batsim_thread.join(timeout=10)
        else:
            # Simulation was truncated / forced stop → need to force-close ZMQ.
            time.sleep(0.5)

        # Step 2: ALWAYS ensure ZMQ context is closed so the port is freed for the next episode!
        if hasattr(self, 'bs') and self.bs is not None:
            try:
                if hasattr(self.bs, 'jobs'):
                    self.bs.jobs.clear()
                if hasattr(self.bs, 'network'):
                    if hasattr(self.bs.network, 'socket') and self.bs.network.socket is not None:
                        try:
                            import zmq
                            self.bs.network.socket.setsockopt(zmq.LINGER, 0)
                        except Exception:
                            pass
                    self.bs.network.close()
            except Exception:
                pass
            self.bs = None

        # Step 3: kill subprocess
        if self._batsim_proc is not None:
            if self._batsim_proc.poll() is None:  # still running
                self._batsim_proc.terminate()
                try:
                    self._batsim_proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._batsim_proc.kill()
                    self._batsim_proc.wait()
            self._batsim_proc = None

        # Step 4: join thread (longer timeout for clean shutdown)
        if self._batsim_thread is not None and self._batsim_thread.is_alive():
            self._batsim_thread.join(timeout=5)
            if self._batsim_thread.is_alive():
                # If still alive, it's likely stuck in ZMQ poll/recv.
                # Since we are daemon=True, it will die with the process,
                # but we've already closed its socket which should trigger an error soon.
                pass
        self._batsim_thread = None

    def _restart_batsim_container(self, timeout: float = 15.0) -> bool:
        """Restart BatSim Docker container via Docker Engine API (Unix socket).

        This allows the Python process inside the 'shell' container to
        programmatically restart the 'batsim' container for each eval episode.
        Requires /var/run/docker.sock mounted into the shell container.
        """
        import http.client
        import socket as _socket

        container = os.environ.get("BATSIM_CONTAINER", "pybatgym-batsim-1")
        sock_path = "/var/run/docker.sock"

        if not Path(sock_path).exists():
            print(
                f"[RealBatsimAdapter] Docker socket not found at {sock_path}.\n"
                "  Mount it in docker-compose.yml:\n"
                "    volumes:\n"
                "      - /var/run/docker.sock:/var/run/docker.sock"
            )
            return False

        try:
            # Connect to Docker daemon via Unix socket
            conn = http.client.HTTPConnection("localhost", timeout=int(timeout))
            sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            sock.connect(sock_path)
            sock.settimeout(timeout)
            conn.sock = sock

            # Docker API: POST /containers/{name}/restart?t=2
            conn.request("POST", f"/containers/{container}/restart?t=2")
            resp = conn.getresponse()
            _ = resp.read()
            conn.close()

            if resp.status == 204:
                print(f"[RealBatsimAdapter] Restarted container '{container}' ✓")
                return True
            else:
                print(f"[RealBatsimAdapter] Container restart failed: HTTP {resp.status}")
                return False

        except Exception as exc:
            print(f"[RealBatsimAdapter] Cannot restart container: {exc}")
            return False

    def _clear_state(self) -> None:
        self._internal_time = 0.0
        self._is_done = False
        self._pending_jobs = []
        self._running_jobs = []
        self._completed_jobs = []
        self._events = []
        self._resource = self._make_resource()
        self._batsim_job_id_map = {}
        # Drain queues
        for q in (self._action_queue, self._state_queue):
            while not q.empty():
                q.get_nowait()

    def _consume_events(self) -> list[Event]:
        events, self._events = self._events, []
        return events

    def _wait_for_next_state(self, timeout: float = 90.0) -> None:
        """Block main thread until pybatsim yields control."""
        try:
            status = self._state_queue.get(timeout=timeout)
            if status == "DONE":
                self._is_done = True
        except queue.Empty:
            print(
                f"[RealBatsimAdapter] Timeout ({timeout}s) waiting for BatSim. "
                "The BatSim container may have taken too long to connect or crashed."
            )
            self._is_done = True

    def _resolve_paths(self) -> tuple[str, str]:
        """Return (platform_path, workload_path) resolving config or defaults."""
        p_cfg = getattr(self.config.platform, "platform_path", None)
        platform = p_cfg if p_cfg and Path(p_cfg).exists() else str(_DEFAULT_PLATFORM)
        
        trace = self.config.workload.trace_path or ""
        workload = trace if trace and Path(trace).exists() else str(_DEFAULT_WORKLOAD)
        
        return platform, workload

    def _start_batsim_subprocess(self) -> None:
        """Spawn the BatSim C++ process (local binary mode).

        Fix 3: When running a local batsim binary, select a free port
        per episode so back-to-back resets don't collide on port 28000.
        External mode (docker-compose batsim) keeps the hardcoded endpoint
        because batsim_start.sh uses tcp://shell:28000.
        """
        platform, workload = self._resolve_paths()

        # Auto-detect batsim binary
        try:
            batsim_bin = _find_batsim()
        except FileNotFoundError:
            # External mode: restart the BatSim Docker container
            print(
                "[RealBatsimAdapter] Local 'batsim' binary not found. "
                "Restarting BatSim Docker container..."
            )
            self._restart_batsim_container()
            return

        # Fix 3: pick a free port so consecutive resets don't hit port conflicts
        free_port = self._find_free_port(self._default_port)
        self.socket_endpoint = f"tcp://*:{free_port}"
        socket_addr = f"tcp://localhost:{free_port}"

        Path("logs").mkdir(exist_ok=True)
        cmd = [batsim_bin, "-p", platform, "-w", workload, "-e", "logs/batsim_out", "-s", socket_addr]

        print(f"[RealBatsimAdapter] Starting BatSim on port {free_port}: {' '.join(cmd)}")
        try:
            self._batsim_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print(f"[RealBatsimAdapter] BatSim PID: {self._batsim_proc.pid}")
        except FileNotFoundError as exc:
            print(f"[RealBatsimAdapter] ERROR launching BatSim: {exc}")
            self._is_done = True

    @staticmethod
    def _patch_pybatsim():
        """Monkey-patch pybatsim to bypass the running_simulation assertion.

        pybatsim 3.1.0 `_read_bat_msg()` has:
            assert not self.running_simulation, "A simulation is already running ..."
        This fires when the previous simulation wasn't cleanly shut down (ZMQ
        force-close leaves running_simulation=True).

        Fix: patch _read_bat_msg to force-reset running_simulation before
        processing SIMULATION_BEGINS.
        """
        try:
            import batsim.batsim as _bmod
            if getattr(_bmod.Batsim, '_patched', False):
                return

            _original_read = _bmod.Batsim._read_bat_msg

            def _patched_read(self):
                # Force-clear the flag so the assertion in SIMULATION_BEGINS
                # handler never fires
                self.running_simulation = False
                return _original_read(self)

            _bmod.Batsim._read_bat_msg = _patched_read
            _bmod.Batsim._patched = True
            print("[RealBatsimAdapter] Patched pybatsim running_simulation guard ✓")
        except (ImportError, AttributeError):
            pass

    def _start_pybatsim_thread(self) -> None:
        """Start pybatsim ZeroMQ server in background thread."""
        self._patch_pybatsim()

        def _run() -> None:
            try:
                import batsim.batsim as _bmod
                bs = _bmod.Batsim(self, self.socket_endpoint, timeout=120)
                bs.start()
                # Give BatSim a moment to receive the final ACK and exit cleanly
                import time; time.sleep(1)
            except Exception as exc:
                # "Connection not open" is expected when _kill_simulation
                # force-closes ZMQ during cleanup — suppress it.
                msg = str(exc)
                if "Connection not open" not in msg and "NoneType" not in msg:
                    print(f"[BatSim thread] Exception: {exc}")
            finally:
                self._is_done = True
                try:
                    self._state_queue.put_nowait("DONE")
                except Exception:
                    pass

        self._batsim_thread = threading.Thread(target=_run, daemon=True, name="pybatsim")
        self._batsim_thread.start()

    # --------------------------------------------------------------------------
    # PyBatsim scheduler callbacks (called from background thread)
    #
    # Architecture: pybatsim processes ONE message at a time:
    #   1. _read_bat_msg() → onBeforeEvents()
    #   2. for each event: onJobSubmission / onJobCompletion / etc.
    #   3. onNoMoreEvents()  ← WE SYNCHRONIZE WITH RL AGENT HERE
    #   4. pybatsim sends accumulated _events_to_send back to BatSim
    #
    # Key insight: we must NOT block in onJobSubmission, because pybatsim
    # hasn't finished processing the message yet.  Instead we accumulate
    # state changes and do the RL round-trip in onNoMoreEvents.
    # --------------------------------------------------------------------------

    # Flag: did anything interesting happen in this message cycle?
    _needs_wakeup: bool = False

    def onDeadlock(self) -> None:
        """Override default: do NOT raise. Just pause briefly and retry.
        PyBatSim 3.1.0 uses non-blocking recv during simulation — returning
        None is normal when BatSim is still processing our EXECUTE_JOB.
        """
        import time
        time.sleep(0.005)

    def onSimulationBegins(self) -> None:
        self._free_cores = set(range(self.bs.nb_compute_resources))
        self._needs_wakeup = False
        # Luôn hiển thị log tiến trình BatSim trong quá trình eval
        self._batsim_verbose = True
        if self._batsim_verbose:
            import sys
            print(f"\n  [BatSim] Simulation begins — {self.bs.nb_compute_resources} cores, verbose ON", flush=True)
        self._state_queue.put("READY")

    def onBeforeEvents(self) -> None:
        self._needs_wakeup = False

    def onNoMoreJobsInWorkloads(self) -> None:
        self.bs.no_more_static_jobs = True

    def onJobSubmission(self, job) -> None:
        """Accumulate submitted job — do NOT block here."""
        cluster_cores = self.bs.nb_compute_resources
        if job.requested_resources > cluster_cores:
            self.bs.reject_jobs([job])
            return

        job_id_str = job.id.split("!")[-1] if "!" in job.id else job.id
        try:
            job_id = int(job_id_str)
        except ValueError:
            job_id = hash(job_id_str)
        self._batsim_job_id_map[job_id] = job.id

        py_job = Job(
            job_id=job_id,
            submit_time=job.submit_time,
            requested_walltime=job.requested_time,
            actual_runtime=job.requested_time,
            requested_resources=job.requested_resources,
        )
        self._pending_jobs.append(py_job)
        self._events.append(Event(EventType.JOB_SUBMITTED, self._internal_time, job=py_job))
        self._needs_wakeup = True
        if self._batsim_verbose:
            print(f"  [BatSim t={job.submit_time:.1f}] JOB_SUBMIT  #{py_job.job_id:3d} | cores={py_job.requested_resources} | walltime={py_job.actual_runtime:.1f}s", flush=True)

    def onJobCompletion(self, job) -> None:
        """Record job completion — do NOT block here."""
        job_id_str = job.id.split("!")[-1] if "!" in job.id else job.id
        py_job = next(
            (j for j in self._running_jobs if str(j.job_id) == job_id_str), None
        )
        if py_job:
            if hasattr(py_job, "allocated_core_set"):
                self._free_cores.update(py_job.allocated_core_set)
            py_job.status = JobStatus.COMPLETED
            py_job.finish_time = self._internal_time
            if py_job.start_time is not None:
                py_job.actual_runtime = max(0.0, py_job.finish_time - py_job.start_time)
            self._running_jobs.remove(py_job)
            self._completed_jobs.append(py_job)
            self._resource.release(py_job.requested_resources)
            self._events.append(Event(EventType.JOB_COMPLETED, self._internal_time, job=py_job))
            if self._batsim_verbose:
                n_done = len(self._completed_jobs)
                n_total = n_done + len(self._running_jobs) + len(self._pending_jobs)
                print(f"  [BatSim t={self._internal_time:7.1f}] JOB_DONE    #{py_job.job_id:3d} | wait={py_job.waiting_time:.1f}s | run={py_job.actual_runtime:.1f}s | done={n_done}/{n_total}", flush=True)
        self._needs_wakeup = True

    def onNoMoreEvents(self) -> None:
        """Called after all events in a BatSim message are processed.

        This is the synchronization point: we wake the RL agent, let it
        make scheduling decisions (possibly multiple per round), and
        accumulate all EXECUTE_JOB commands before pybatsim sends the
        response back to BatSim.
        """
        if not self._needs_wakeup:
            return
        if not hasattr(self, 'bs') or self.bs is None:
            return

        self._internal_time = self.bs.time()

        execute_batch = []
        # Scheduling loop: keep asking the RL agent until it sends WAIT
        # or there are no more pending jobs. This lets the agent schedule
        # multiple jobs per BatSim decision point.
        max_rounds = len(self._pending_jobs) + 1  # safety cap
        for _ in range(max(1, max_rounds)):
            self._state_queue.put("WAKEUP")
            cmds: list[Optional[ScheduleCommand]] = self._action_queue.get()

            did_execute = False
            for cmd in cmds:
                if not cmd:
                    continue
                if cmd.command_type == ScheduleCommandType.WAIT:
                    # Agent explicitly chose WAIT — stop the scheduling loop
                    break
                if cmd.command_type == ScheduleCommandType.EXECUTE_JOB and cmd.job:
                    if cmd.job not in self._pending_jobs:
                        continue
                    full_batsim_id = self._batsim_job_id_map.get(cmd.job.job_id)
                    batsim_jobs = getattr(self.bs, "jobs", {})
                    if full_batsim_id and full_batsim_id in batsim_jobs:
                        actual_job = batsim_jobs[full_batsim_id]
                        req_cores = cmd.job.requested_resources
                        if len(self._free_cores) < req_cores:
                            continue  # not enough cores right now
                        alloc = set(list(self._free_cores)[:req_cores])
                        self._free_cores.difference_update(alloc)
                        cmd.job.allocated_core_set = alloc

                        from procset import ProcSet
                        actual_job.allocation = ProcSet(*alloc)
                        execute_batch.append(actual_job)

                        cmd.job.status = JobStatus.RUNNING
                        cmd.job.start_time = self._internal_time
                        self._pending_jobs.remove(cmd.job)
                        self._running_jobs.append(cmd.job)
                        if self._resource.can_allocate(cmd.job.requested_resources):
                            self._resource.allocate(cmd.job.requested_resources)
                        did_execute = True
            else:
                # for-loop didn't break (no WAIT cmd) — check if we should continue
                if not did_execute or not self._pending_jobs:
                    break
                continue  # did_execute=True and pending jobs remain → next round

            # for-loop broke (WAIT cmd received) — exit scheduling loop
            break

        if execute_batch:
            self.bs.execute_jobs(execute_batch)

        # Deadlock prevention: if pending jobs remain but NO jobs are running,
        # BatSim will deadlock (no future events to trigger JOB_COMPLETED).
        # Use wake_me_up_at to request a callback so we get another chance.
        # Increased to 10.0s to reduce ZMQ flooding/assertion risks.
        if self._pending_jobs and not self._running_jobs and self.bs is not None:
            self.bs.wake_me_up_at(self.bs.time() + 10.0)

    def onRequestedCall(self) -> None:
        """Handle CALL_ME_LATER callback — retry scheduling pending jobs."""
        self._needs_wakeup = True

    def onSimulationEnds(self) -> None:
        if getattr(self, '_batsim_verbose', False):
            print(f"  [BatSim] Simulation ENDS at t={self._internal_time:.1f}s", flush=True)
        self._state_queue.put("DONE")
