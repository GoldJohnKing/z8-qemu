#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The experimental patched-MAIN option pins exactly one local image.

Default acceptance stays pinned to the original Z8 MAIN; the explicit
--experimental-main-sha256 option replaces the pin with exactly the given
digest (a locally built patched image) and nothing looser.
"""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from runtime import experimental_sha256, verify

class ExperimentalMainPin(unittest.TestCase):
    def test_sha256_normalizer(self):
        digest = 'a'*64
        self.assertEqual(experimental_sha256(digest.upper()), digest)
        for bad in ('', 'z'*64, 'a'*63, 'a'*65, None):
            with self.assertRaises(ValueError):
                experimental_sha256(bad)

    def test_default_pin_rejects_wrong_image(self):
        with tempfile.TemporaryDirectory() as temp:
            wrong = Path(temp)/'wrong.bi'
            wrong.write_bytes(b'\0'*81807709)      # stock size, wrong digest
            with self.assertRaises(ValueError):
                verify(wrong)
            short = Path(temp)/'short.bi'
            short.write_bytes(b'\0'*4096)
            with self.assertRaises(ValueError):
                verify(short)

    def test_experimental_pin_accepts_only_the_pinned_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp)/'patched.bi'
            payload = b'local patched payload'.ljust(81807709, b'\0')
            image.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            firmware, manifest = verify(image, allow_main_sha256=digest.upper())
            self.assertEqual(firmware, image.resolve())
            self.assertIsInstance(manifest, dict)
            with self.assertRaises(ValueError):
                verify(image, allow_main_sha256='b'*64)
            short = Path(temp)/'short.bi'
            short.write_bytes(b'local patched payload')
            with self.assertRaises(ValueError):
                verify(short, allow_main_sha256=hashlib.sha256(b'local patched payload').hexdigest())

    def test_run_native_help_offers_only_the_local_experiment_wording(self):
        result = subprocess.run(
            [sys.executable, str(ROOT/'tools/run_native.py'), '--help'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--experimental-main-sha256', result.stdout)
        self.assertIn('Local experiment only', result.stdout)
        self.assertIn('patched Z8 MAIN', result.stdout)

    def test_run_native_rejects_malformed_pin_before_touching_materials(self):
        for bad in ('nothex', 'a'*63):
            result = subprocess.run(
                [sys.executable, str(ROOT/'tools/run_native.py'),
                 '--firmware', 'missing.bi', '--qemu', 'missing',
                 '--raw', 'missing', '--output', 'missing-out',
                 '--mcu', 'missing-mcu',
                 '--experimental-main-sha256', bad, '--check-only'],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, bad)

    def test_run_native_check_only_with_local_patched_image(self):
        materials = [ROOT/'.local/runs/e2c-patch/patched-main.bi',
                     ROOT/'.local/ex2070_030000.bi',
                     ROOT/'.local/build/qemu-system-aarch64',
                     ROOT/'.local/liveview.raw']
        if not all(path.is_file() for path in materials):
            self.skipTest('local patched MAIN / EX / QEMU materials not present')
        digest = hashlib.sha256(materials[0].read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(ROOT/'tools/run_native.py'),
                 '--firmware', str(materials[0]), '--mcu', str(materials[1]),
                 '--qemu', str(materials[2]), '--raw', str(materials[3]),
                 '--output', str(Path(temp)/'out'),
                 '--experimental-main-sha256', digest, '--check-only'],
                capture_output=True, text=True)
            self.assertIn('verified', result.stdout, result.stderr)
            self.assertEqual(result.returncode, 0)

if __name__ == '__main__':
    unittest.main()
