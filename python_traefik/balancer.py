from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Backend:
    url: str
    healthy: bool = True


class RoundRobinBalancer:
    def __init__(self, backends: List[Backend]):
        if not backends:
            raise ValueError("Service must have at least one backend server.")
        self.backends = backends
        self._cycle = itertools.cycle(range(len(backends)))

    def next_backend(self) -> Optional[Backend]:
        # Try up to N backends to find a healthy one
        for _ in range(len(self.backends)):
            idx = next(self._cycle)
            b = self.backends[idx]
            if b.healthy:
                return b
        return None
