from __future__ import annotations
from typing import Optional

import numpy as np


class RandomMaskedPolicy:
    """Policy ngẫu nhiên chỉ chọn trong các action hợp lệ theo action mask.

    - Không dùng action SCHEDULE_SMALLEST_FITTING (index cuối) để không "mượn" heuristic.
    - Không chọn WAIT khi còn job vừa core rảnh mà không có job nào đang chạy, vì khi đó WAIT
      có thể làm mô phỏng nhảy thẳng tới cuối và bỏ dở các job còn chờ.
    - Tái lập được: cùng seed thì cùng chuỗi action.
    """

    name = "random_masked"

    def __init__(self, seed: int = 0) -> None:
        self.reset(seed)

    def reset(self, seed: Optional[int] = None) -> None:
        self._rng = np.random.default_rng(seed)

    def __call__(self, env) -> int:
        mask = np.asarray(env.action_masks(), dtype=bool).copy()
        wait = env.action_space.n - 2
        mask[-1] = False  # SCHEDULE_SMALLEST_FITTING
        any_job_fits = bool(mask[:wait].any())
        nothing_running = env._state["resource"].used_cores == 0
        if any_job_fits and nothing_running:
            mask[wait] = False
        valid = np.flatnonzero(mask)
        if valid.size == 0:
            return wait
        return int(self._rng.choice(valid))


def random_masked_policy(env, _policy=RandomMaskedPolicy(0)) -> int:
    """Phiên bản hàm (seed cố định 0) để tiện dùng như các baseline khác."""
    return _policy(env)
