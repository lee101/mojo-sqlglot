"""ctypes bridge to the Mojo lexical scanner."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get("MOJOSQLGLOT_LIB") or os.path.join(
    ROOT, "dist", "libmojo-sqlglot.so"
)
SRC = os.path.join(ROOT, "src", "sqlglot.mojo")

I = ctypes.c_int64
_lib: ctypes.CDLL | None = None


class BuildError(RuntimeError):
    pass


def build(force: bool = False) -> str:
    if os.environ.get("MOJOSQLGLOT_LIB") and os.path.exists(LIB) and not force:
        return LIB
    if not force and os.path.exists(LIB) and os.path.getmtime(LIB) >= os.path.getmtime(SRC):
        return LIB
    pixi = shutil.which("pixi")
    if not pixi:
        raise BuildError("pixi not found; run `pixi run build` or set MOJOSQLGLOT_LIB")
    proc = subprocess.run(
        [pixi, "run", "--manifest-path", os.path.join(ROOT, "pixi.toml"), "build"],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode or not os.path.exists(LIB):
        raise BuildError((proc.stderr or proc.stdout).strip()[:4000])
    return LIB


def lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(build())
        _lib.msg_tokenize.argtypes = [I, I, I, I, I, I]
        _lib.msg_tokenize.restype = I
    return _lib


def scan(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not isinstance(data, bytes):
        raise TypeError("scan input must be bytes")
    source = np.frombuffer(data, dtype=np.uint8)
    capacity = max(1, len(data))
    spans = np.empty((3, capacity), dtype=np.int64)
    starts, ends, kinds = spans
    count = lib().msg_tokenize(
        source.ctypes.data,
        source.size,
        starts.ctypes.data,
        ends.ctypes.data,
        kinds.ctypes.data,
        capacity,
    )
    # source and spans remain strongly referenced until ctypes returns. The
    # Mojo scanner is synchronous and does not retain any of their addresses.
    if count == -2:
        raise RuntimeError("native tokenizer rejected invalid buffer metadata")
    if count == -3:
        raise RuntimeError("unterminated SQL string, identifier, or block comment")
    if count < 0:
        raise RuntimeError("token output capacity exhausted")
    if count > capacity:
        raise RuntimeError("native tokenizer returned an invalid token count")
    return starts[:count], ends[:count], kinds[:count]
