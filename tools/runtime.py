# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
# Copyright (C) 2026 GoldJohnKing: experimental patched-MAIN pin.
"""Explicit local runtime paths; no Nikon inputs are distributed."""
from pathlib import Path
import argparse, hashlib, json
ROOT = Path(__file__).resolve().parents[1]
MAIN_SHA = "2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853"

def arguments(description, capture=False):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--firmware', type=Path, required=True)
    p.add_argument('--qemu', type=Path, required=True)
    p.add_argument('--raw', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True, help='Fresh run directory')
    return p

def experimental_sha256(value):
    """Validate an explicit pinned sha256 for a local patched-MAIN experiment."""
    allowed = (value or '').strip().lower()
    if len(allowed) != 64 or any(c not in '0123456789abcdef' for c in allowed):
        raise ValueError('Expected a 64-hex-character experimental MAIN sha256')
    return allowed

def verify(firmware, allow_main_sha256=None):
    firmware = firmware.resolve()
    if allow_main_sha256 is not None:
        # Local-experiment path: accept exactly the pinned patched image,
        # original payload size included, so the preflight check is as
        # strict as the guest layer's boot-time re-check.
        allowed = experimental_sha256(allow_main_sha256)
        if firmware.stat().st_size != 81807709 or hashlib.file_digest(firmware.open('rb'), 'sha256').hexdigest() != allowed:
            raise ValueError('Expected the pinned experimental MAIN payload (original size, CRC trailer excluded)')
        return firmware, json.loads((ROOT/'source-manifest.json').read_text())
    if firmware.stat().st_size != 81807709 or hashlib.file_digest(firmware.open('rb'), 'sha256').hexdigest() != MAIN_SHA:
        raise ValueError('Expected original Z8 C3.11 MAIN payload (CRC trailer excluded)')
    return firmware, json.loads((ROOT/'source-manifest.json').read_text())
