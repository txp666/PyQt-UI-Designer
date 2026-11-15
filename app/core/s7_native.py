"""Thin ctypes C-ABI adapter for the pinned native Snap7 library (LGPL-3.0-or-later).

No python-snap7 package is used. A client belongs exclusively to its I/O worker.
"""
import ctypes
from pathlib import Path
import sys

from .s7_values import decode_s7, encode_s7, parse_s7_address


SNAP7_COMMIT = "30f37da3114024a71ba93f7fd855c680b97a406f"
LIBRARY_NAME = "snap7.dll" if sys.platform == "win32" else "libsnap7.dylib" if sys.platform == "darwin" else "libsnap7.so"


def native_library_path():
    module = Path(__file__).resolve()
    candidates = [module.parent / "native" / LIBRARY_NAME,
                  module.parents[2] / "native" / LIBRARY_NAME,
                  module.parents[2] / "app" / "resource" / "native" / LIBRARY_NAME]
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("Snap7 native library is missing. Run scripts/build_snap7.py before using S7.")


class S7Error(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NativeS7Client:
    def __init__(self, library=None):
        path = str(library or native_library_path())
        self._library = ctypes.WinDLL(path) if sys.platform == "win32" else ctypes.CDLL(path)
        handle = ctypes.c_size_t
        pointer = ctypes.c_void_p
        signatures = {
            "Cli_Create": (handle, []), "Cli_Destroy": (None, [ctypes.POINTER(handle)]),
            "Cli_ConnectTo": (ctypes.c_int, [handle, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]),
            "Cli_SetConnectionType": (ctypes.c_int, [handle, ctypes.c_uint16]),
            "Cli_SetParam": (ctypes.c_int, [handle, ctypes.c_int, pointer]),
            "Cli_Disconnect": (ctypes.c_int, [handle]),
            "Cli_ReadArea": (ctypes.c_int, [handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, pointer]),
            "Cli_WriteArea": (ctypes.c_int, [handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, pointer]),
            "Cli_GetPduLength": (ctypes.c_int, [handle, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]),
            "Cli_ErrorText": (ctypes.c_int, [ctypes.c_int, pointer, ctypes.c_int]),
        }
        for name, (result, arguments) in signatures.items():
            method = getattr(self._library, name)
            method.restype, method.argtypes = result, arguments
        self._handle = handle(self._library.Cli_Create())
        if not self._handle.value:
            raise RuntimeError("Cannot create a Snap7 client")

    def _check(self, code):
        if code:
            message = ctypes.create_string_buffer(512)
            self._library.Cli_ErrorText(code, message, len(message))
            raise S7Error(code, message.value.decode("utf-8", errors="replace") + f" (0x{code:08x})")

    def connect(self, config):
        port = ctypes.c_uint16(config["port"])
        self._check(self._library.Cli_SetParam(self._handle, 2, ctypes.byref(port)))
        for parameter in (3, 4, 5):  # Ping/Send/Recv timeout; connection patch makes TCP connect bounded.
            timeout = ctypes.c_int32(config["timeout"])
            self._check(self._library.Cli_SetParam(self._handle, parameter, ctypes.byref(timeout)))
        self._check(self._library.Cli_SetConnectionType(self._handle, config["connectionType"]))
        self._check(self._library.Cli_ConnectTo(self._handle, config["host"].encode("ascii"), config["rack"], config["slot"]))

    def read(self, point):
        address = parse_s7_address(point["address"], point["dataType"])
        data = (ctypes.c_ubyte * address.size)()
        self._check(self._library.Cli_ReadArea(self._handle, address.area, address.db, address.offset,
                                             address.size, 2, data))
        return decode_s7(bytes(data), point["dataType"], address.bit if address.bit >= 0 else 0)

    def write(self, point, value):
        address = parse_s7_address(point["address"], point["dataType"])
        encoded = encode_s7(value, point["dataType"])
        data = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        bit = address.bit >= 0
        start = address.offset * 8 + address.bit if bit else address.offset
        self._check(self._library.Cli_WriteArea(self._handle, address.area, address.db, start,
                                              1 if bit else len(encoded), 1 if bit else 2, data))

    def close(self):
        if self._handle.value:
            self._library.Cli_Disconnect(self._handle)
            self._library.Cli_Destroy(ctypes.byref(self._handle))
