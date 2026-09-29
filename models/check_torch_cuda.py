"""Check the active Python's PyTorch installation and run CPU/CUDA operations.

Run from Anaconda Prompt:
    conda activate waam-ppo
    python models/check_torch_cuda.py
    python models/check_torch_cuda.py --require-cuda

Exit codes: 0 = available devices passed (CPU-only is allowed by default),
1 = PyTorch import or CPU test failed, 2 = required CUDA is unavailable,
3 = CUDA initialization or a GPU operation failed.
No project dependencies other than PyTorch are needed; no files are written.
"""

from __future__ import annotations

import argparse
import sys


def check_matmul(torch, device: str) -> None:
    """Allocate on the selected device and verify a small matrix product."""
    with torch.no_grad():
        matrix = torch.ones((2, 2), device=device)
        result = matrix @ matrix
        if device.startswith("cuda"):
            # CUDA work is asynchronous; wait to surface kernel errors here.
            torch.cuda.synchronize(device)
        expected = torch.full((2, 2), 2.0, device=device)
        if not torch.allclose(result, expected):
            raise RuntimeError(f"Incorrect matrix multiplication result on {device}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check PyTorch installation and CUDA execution")
    parser.add_argument(
        "--require-cuda", action="store_true",
        help="Return a nonzero exit code if CUDA is unavailable",
    )
    args = parser.parse_args(argv)
    print(f"Python executable : {sys.executable}")
    print(f"Python version    : {sys.version.split()[0]}")

    try:
        import torch
    except ModuleNotFoundError as exc:
        if exc.name == "torch":
            print("[FAIL] PyTorch is not installed in this Python environment.")
            print("Activate the intended conda environment and install PyTorch there.")
        else:
            print(f"[FAIL] A PyTorch dependency is missing: {exc}")
        return 1
    except Exception as exc:
        print(f"[FAIL] PyTorch import failed: {type(exc).__name__}: {exc}")
        return 1

    print(f"PyTorch version   : {torch.__version__}")
    print(f"PyTorch location  : {torch.__file__}")
    print(f"CUDA build version: {torch.version.cuda or 'None (no NVIDIA CUDA build)'}")
    try:
        check_matmul(torch, "cpu")
        print("[PASS] PyTorch CPU tensor operation")
    except Exception as exc:
        print(f"[FAIL] CPU operation: {type(exc).__name__}: {exc}")
        return 1

    try:
        available = torch.cuda.is_available()
        print(f"CUDA available    : {available}")
        if not available:
            print("[UNAVAILABLE] CUDA GPU execution cannot be tested in this environment.")
            if torch.version.cuda is None:
                print("This PyTorch installation has no NVIDIA CUDA support.")
            else:
                print("Check the NVIDIA GPU, driver, and GPU visibility for this process.")
            print("[PASS] CPU is usable. CUDA has not passed a GPU operation test.")
            return 2 if args.require_cuda else 0

        count = torch.cuda.device_count()
        if count < 1:
            raise RuntimeError("CUDA reports available but no GPU is visible")
        print(f"Visible GPU count : {count}")
        for index in range(count):
            device = f"cuda:{index}"
            properties = torch.cuda.get_device_properties(index)
            print(f"{device}: {properties.name}")
            print(f"  VRAM: {properties.total_memory / (1024 ** 3):.2f} GiB")
            print(f"  Compute capability: {properties.major}.{properties.minor}")
            check_matmul(torch, device)
            print(f"[PASS] {device} allocation, matrix multiplication and synchronization")
    except Exception as exc:
        print(f"[FAIL] CUDA check: {type(exc).__name__}: {exc}")
        return 3

    print("[PASS] PyTorch CPU and all visible CUDA GPUs passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
