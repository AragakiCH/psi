import threading
from collections import deque
from typing import Deque, Dict, List, Optional

class DataBuffer:
    def __init__(self, maxlen: int = 5000) -> None:
        self._lock = threading.Lock()
        self._dq: Deque[Dict] = deque(maxlen=maxlen)
        self._seq: int = 0

    def append(self, sample: Dict) -> int:
        """Añade un sample y le mete __seq__ para poder mandar sólo lo nuevo."""
        with self._lock:
            self._seq += 1
            s = dict(sample)
            s["__seq__"] = self._seq
            self._dq.append(s)
            return self._seq

    def after(self, last_seq: Optional[int]) -> List[Dict]:
        """Devuelve todos los samples con seq > last_seq."""
        with self._lock:
            if last_seq is None:
                return list(self._dq)
            return [s for s in self._dq if s.get("__seq__", 0) > last_seq]

    def __len__(self) -> int:
        with self._lock:
            return len(self._dq)

    def clear(self) -> None:
        with self._lock:
            self._dq.clear()

data_buffer = DataBuffer(maxlen=5000)
