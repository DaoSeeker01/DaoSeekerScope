"""Call the C API from Python. Pass a path to the built shared library."""

from __future__ import annotations

import argparse
import ctypes as c
import json


class Buffer(c.Structure):
    _fields_ = [
        ("data", c.POINTER(c.c_uint8)),
        ("len", c.c_size_t),
        ("token", c.c_uint64),
    ]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", help="shared library path")
    library = c.CDLL(parser.parse_args().library)
    library.dsc_abi_version.restype = c.c_uint32
    library.dsc_collect_json.argtypes = [c.c_void_p, c.POINTER(Buffer)]
    library.dsc_collect_json.restype = c.c_int32
    library.dsc_buffer_free.argtypes = [c.POINTER(Buffer)]
    library.dsc_buffer_free.restype = c.c_int32
    library.dsc_last_error.restype = c.c_char_p
    require(library.dsc_abi_version() == 1, "unsupported ABI")
    for _ in range(100):
        buffer = Buffer()
        code = library.dsc_collect_json(None, c.byref(buffer))
        require(code == 0, "collection failed")
        try:
            require(
                bool(buffer.data) and buffer.len > 0 and buffer.token != 0,
                "invalid buffer",
            )
            snapshot = json.loads(c.string_at(buffer.data, buffer.len))
            require(snapshot["schema_version"] == 1, "unsupported schema")
            # Field availability depends on the host; the example accepts
            # legitimate unavailable values instead of requiring a CPU brand.
            require(
                snapshot["static_info"]["system"]["device"]["serial_number"]["value"]
                is None,
                "privacy failure",
            )
            stale = Buffer(buffer.data, buffer.len, buffer.token)
        finally:
            require(library.dsc_buffer_free(c.byref(buffer)) == 0, "free failed")
        require(
            not buffer.data and buffer.len == 0 and buffer.token == 0,
            "buffer not zeroed",
        )
        require(library.dsc_buffer_free(c.byref(buffer)) == 0, "empty free failed")
        require(library.dsc_buffer_free(c.byref(stale)) == 9, "stale buffer accepted")
    print(
        "ctypes: 100 real collect/free cycles, stale copy rejection, privacy and schema passed"
    )


if __name__ == "__main__":
    main()
