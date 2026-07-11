"""Shared Cellpose runtime helpers.

This keeps the analysis scripts consistent when selecting CPU vs GPU mode.
"""

from __future__ import annotations

import os


def resolve_cellpose_gpu_mode(default: str = "auto") -> bool:
    """Return whether Cellpose should try to use a GPU.

    The `CELLPOSE_GPU` environment variable can force the choice:
    - 1/true/yes/on/gpu -> enable GPU
    - 0/false/no/off/cpu -> disable GPU
    - auto (default) -> use CUDA if PyTorch reports it is available
    """

    raw_value = os.getenv("CELLPOSE_GPU", default).strip().lower()

    if raw_value in {"1", "true", "yes", "on", "gpu"}:
        return True
    if raw_value in {"0", "false", "no", "off", "cpu"}:
        return False
    if raw_value != "auto":
        raise ValueError(
            "CELLPOSE_GPU must be one of: auto, 1/true/yes/on/gpu, 0/false/no/off/cpu"
        )

    try:
        import torch
    except ImportError:
        return False

    return bool(torch.cuda.is_available())