import struct
from pybatgym.runner.docker_runtime import log_text


def test_large_multiplexed_log_preserves_all_frames_and_plain_tail():
    messages = [f"job {i}: hoàn tất\n".encode() for i in range(20000)]
    payload = b"".join(bytes([1 + i % 2, 0, 0, 0]) + struct.pack(">I", len(m)) + m for i, m in enumerate(messages))
    assert log_text(payload + b"tail") == b"".join(messages).decode() + "tail"
    assert log_text(b"plain log") == "plain log"
    assert log_text(b"") == ""
