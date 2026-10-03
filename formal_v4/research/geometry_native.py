"""NumPy/ctypes interface to the fixed-plane native geometry sweep.

No compiler, Numba, C++ runtime, subprocess or network is used when calling it.
Supply a prebuilt library beside this file or set GEOMETRY_NATIVE_LIBRARY to
its path. Research builds also look in results/geometry_native_20261003.
"""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import platform
import numpy as np

_LIB = None
_LIB_PATH = None


def library_filename():
    system, machine = platform.system().lower(), platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    suffix = "dylib" if system == "darwin" else "so"
    return f"geometry_native_{system}_{machine}.{suffix}"


def load_library(path=None):
    """Load once, fail explicitly if the platform's prebuilt binary is absent."""
    global _LIB, _LIB_PATH
    requested = path or os.environ.get("GEOMETRY_NATIVE_LIBRARY")
    if _LIB is not None and (requested is None or Path(requested).resolve() == _LIB_PATH):
        return _LIB
    here = Path(__file__).resolve().parent
    candidates = [Path(requested)] if requested else [
        here / library_filename(),
        here.parent / "results" / "geometry_native_20261003" / library_filename(),
    ]
    found = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if found is None:
        raise RuntimeError("Prebuilt native geometry library missing: " + ", ".join(str(p) for p in candidates))
    lib = ctypes.CDLL(str(found))
    lib.geometry_native_abi_version.argtypes = []
    lib.geometry_native_abi_version.restype = ctypes.c_int
    if lib.geometry_native_abi_version() != 1:
        raise RuntimeError("Unsupported native geometry ABI")
    array = np.ctypeslib.ndpointer(dtype=np.float64, flags=("C_CONTIGUOUS", "ALIGNED"))
    lib.geometry_weighted_sweep.argtypes = [
        array, array, array, ctypes.c_int64, ctypes.c_int64,
        ctypes.c_double, ctypes.c_double, ctypes.c_int64, ctypes.c_double,
        ctypes.c_int64, array, array, array, ctypes.POINTER(ctypes.c_int64),
    ]
    lib.geometry_weighted_sweep.restype = ctypes.c_int
    _LIB, _LIB_PATH = lib, found
    return lib


def weighted_sweep(x, y, values, pitch, glass, side, radius, keep=3):
    """Return best x/y/value [Q, keep] and number of visited arrangement cells.

    Same sweep and output ordering as candidate_geometry_sweep.weighted_sweep
    for finite float64 inputs and disjoint glass boxes (0.016 < glass <= pitch).
    Conversion, validation, allocation, ctypes and the native call are included.
    """
    x = np.require(x, dtype=np.float64, requirements=("C", "A"))
    y = np.require(y, dtype=np.float64, requirements=("C", "A"))
    values = np.require(values, dtype=np.float64, requirements=("C", "A"))
    if x.ndim != 1 or y.shape != x.shape or values.ndim != 2 or values.shape[1] != len(x):
        raise ValueError("Expected x/y [N] and values [Q,N]")
    side, keep = int(side), int(keep)
    pitch, glass, radius = float(pitch), float(glass), float(radius)
    if side < 1 or keep < 1 or not (0.016 < glass <= pitch) or radius <= 0 or not all(
        math.isfinite(v) for v in (pitch, glass, radius)
    ):
        raise ValueError("Expected side/keep >= 1, finite radius > 0, and 0.016 < glass <= pitch")
    if not (np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(values).all()):
        raise ValueError("Geometry inputs must be finite")
    shape = (len(values), keep)
    bx, by, bv = np.empty(shape), np.empty(shape), np.empty(shape)
    visited = ctypes.c_int64()
    status = load_library().geometry_weighted_sweep(
        x, y, values, len(x), len(values), pitch, glass, side, radius, keep,
        bx, by, bv, ctypes.byref(visited),
    )
    if status == 2:
        raise MemoryError("Native geometry allocation failed")
    if status:
        raise ValueError(f"Native geometry rejected input (status {status})")
    return bx, by, bv, visited.value
