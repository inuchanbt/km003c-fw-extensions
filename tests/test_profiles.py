"""Exact-stock profile metadata and fail-closed build routing."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from pdinfo.overlay207 import STOCK_HASH, LOADER_HASH

ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def test_current_profile_matches_qualified_implementation(self):
        p = json.loads((ROOT / 'firmware/v2.0.7/profile.json').read_text())
        self.assertEqual((p['stock_firmware'], p['hardware']), ('2.0.7', '2.3'))
        self.assertEqual(p['stock_app_sha256'], STOCK_HASH)
        self.assertEqual(p['bootloader_sha256'], LOADER_HASH)
        self.assertEqual(set(p['variants']), {'qr', 'screen'})

    def test_unported_stock_version_cannot_invoke_a_compiler(self):
        r = subprocess.run([sys.executable, str(ROOT / 'tools/build_firmware.py'),
                            '--stock-fw', '2.0.8', '--clang', 'must-not-run'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn('invalid choice', r.stderr)


if __name__ == '__main__':
    unittest.main()
