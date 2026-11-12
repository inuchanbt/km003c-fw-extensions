"""Release privacy and whole-inventory validation use only synthetic bytes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import check_windows_release as release


class ReleaseTests(unittest.TestCase):
    def kit(self, extra=None, duplicate=False):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        archive = Path(folder.name) / 'kit.zip'
        contents = {'Install.ps1': b'\xef\xbb\xbf# synthetic'}
        qualified = {}
        for variant in ('qr', 'screen'):
            parts = [variant.encode() + b'gate', variant.encode() + b'extension']
            qualified[variant] = tuple(hashlib.sha256(x).hexdigest() for x in parts)
            for name, raw in zip(('gate', 'extension'), parts):
                contents[f'overlays/{variant}/{name}.bin'] = raw
        if extra:
            contents.update(extra)
        manifest = dict(schema=1, project_version='test', stock_free=True,
                        installable_firmware_included=False, stock_firmware='2.0.7', hardware='2.3',
                        files=[dict(path=n, bytes=len(b), sha256=hashlib.sha256(b).hexdigest()) for n,b in contents.items()])
        contents['release-manifest.json'] = json.dumps(manifest).encode()
        with ZipFile(archive, 'w') as z:
            for n,b in contents.items():
                z.writestr(n,b)
            if duplicate:
                z.writestr('Install.ps1', contents['Install.ps1'])
        archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  kit.zip\n')
        return archive, qualified

    def test_private_binary_and_parent_paths_are_rejected_even_when_hashes_match(self):
        for extra in ({'stock-app.bin': b'private'}, {'private/restore.mencrypt': b'private'}, {'../escape.txt': b'bad'}):
            archive, qualified = self.kit(extra)
            with patch.object(release, 'QUALIFIED', qualified), self.assertRaises(ValueError):
                release.audit(archive)

    def test_complete_inventory_and_zip_checksum_are_required(self):
        archive, qualified = self.kit()
        with patch.object(release, 'QUALIFIED', qualified):
            release.audit(archive)
            with ZipFile(archive, 'a') as z:
                z.writestr('unlisted.txt', b'bad')
            archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  kit.zip\n')
            with self.assertRaisesRegex(ValueError, 'inventory'):
                release.audit(archive)
            archive.with_suffix('.zip.sha256').write_text('0' * 64 + '  kit.zip\n')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                release.audit(archive)


if __name__ == '__main__':
    unittest.main()
