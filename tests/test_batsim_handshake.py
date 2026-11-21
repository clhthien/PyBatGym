"""A state notification must coincide with the scheduler waiting for an action."""
import threading
from types import SimpleNamespace

from pybatgym.adapters.batsim_adapter import RealBatsimAdapter
from pybatgym.config.base_config import PyBatGymConfig
from pybatgym.core import ScheduleCommand, ScheduleCommandType


def test_simulation_begin_does_not_release_agent_before_decision_barrier():
    adapter = RealBatsimAdapter(PyBatGymConfig())
    adapter.bs = SimpleNamespace(nb_compute_resources=32, time=lambda: 0.0)
    adapter.onSimulationBegins()
    assert adapter._state_queue.empty()
    adapter._needs_wakeup = True
    thread = threading.Thread(target=adapter.onNoMoreEvents, daemon=True)
    thread.start()
    assert adapter._state_queue.get(timeout=2) == "WAKEUP"
    assert thread.is_alive()
    assert adapter._state_queue.empty()
    adapter._action_queue.put([ScheduleCommand(command_type=ScheduleCommandType.WAIT)])
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert adapter._state_queue.empty()
