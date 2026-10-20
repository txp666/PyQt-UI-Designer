"""Bounded display cache with full history spooled to a temporary file."""
from collections import deque
from itertools import islice
import struct
import tempfile


class ChartHistory:
    def __init__(self, capacity=10000):
        self.cache = deque(maxlen=capacity)
        self.count = 0
        self._file = None

    def append(self, value):
        value = float(value)
        if self._file is None:
            self._file = tempfile.TemporaryFile()
        self._file.write(struct.pack("<d", value))
        self.cache.append(value)
        self.count += 1

    def tail(self, count):
        return list(islice(self.cache, max(0, len(self.cache) - count), None))

    def values(self):
        if self._file is None:
            return
        self._file.flush()
        self._file.seek(0)
        try:
            while True:
                chunk = self._file.read(8192)
                if not chunk:
                    break
                yield from (v[0] for v in struct.iter_unpack("<d", chunk))
        finally:
            self._file.seek(0, 2)

    def clear(self):
        self.close()
        self.cache.clear()
        self.count = 0

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None

    def __len__(self):
        return len(self.cache)

    def __getitem__(self, index):
        return self.cache[index]

    def __del__(self):
        self.close()
