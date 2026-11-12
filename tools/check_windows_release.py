"""Audit a Windows ZIP; optional extracted/offline tests never open USB."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from package_windows_release import QUALIFIED
from pdinfo import overlay207


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def audit(archive):
    expected = archive.with_suffix('.zip.sha256').read_text(encoding='ascii').split()
    if expected != [digest(archive.read_bytes()), archive.name]:
        raise ValueError('ZIP checksum mismatch')
    with ZipFile(archive) as z:
        names = z.namelist()
        if len(set(names)) != len(names):
            raise ValueError('Duplicate ZIP names')
        for name in names:
            if '\\' in name or ':' in name or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                raise ValueError('Unsafe ZIP path')
        contents = {name: z.read(name) for name in names}
    manifest = json.loads(contents['release-manifest.json'])
    if (manifest['schema'] != 1 or manifest['stock_free'] is not True
            or manifest['installable_firmware_included'] is not False
            or (manifest['stock_firmware'], manifest['hardware']) != ('2.0.7', '2.3')):
        raise ValueError('Invalid release profile')
    records = {x['path']: x for x in manifest['files']}
    if len(records) != len(manifest['files']) or set(contents) != set(records) | {'release-manifest.json'}:
        raise ValueError('Release file inventory differs')
    for name, record in records.items():
        raw = contents[name]
        if len(raw) != record['bytes'] or digest(raw) != record['sha256']:
            raise ValueError('Release file differs: ' + name)
        suffix = Path(name).suffix.lower()
        if suffix == '.bin' and name not in {f'overlays/{v}/{n}.bin' for v in QUALIFIED for n in ('gate', 'extension')}:
            raise ValueError('Unapproved binary data')
        if suffix in ('.mencrypt', '.bmp', '.elf', '.dll') or any(word in name.lower() for word in ('calibration-', 'stock-app.', 'identity.json', 'loader-0000', 'internal-tail-')):
            raise ValueError('Private or unsupported release file')
        if suffix == '.exe' and (name not in ('km003c-backup.exe', 'km003c-overlay-host.exe') or not raw.startswith(b'MZ')):
            raise ValueError('Unexpected executable')
    for variant, hashes in QUALIFIED.items():
        if tuple(digest(contents[f'overlays/{variant}/{name}.bin']) for name in ('gate', 'extension')) != hashes:
            raise ValueError('Components differ from qualified variant')
    if not contents['Install.ps1'].startswith(b'\xef\xbb\xbf'):
        raise ValueError('PowerShell 5.1 UTF-8 BOM is missing')
    return contents, manifest


def run(command, env, *, good=True, input=None):
    result = subprocess.run([str(x) for x in command], env=env, input=input,
                            capture_output=True, text=True, errors='replace', timeout=120)
    if (result.returncode == 0) != good:
        # Do not print private backup contents in CI or release output.
        raise RuntimeError(f'Unexpected result for {Path(command[0]).name}: exit {result.returncode}; {result.stderr[-1000:]}')
    return result


def smoke(folder, stock=None):
    env = os.environ.copy()
    system = Path(os.environ['SystemRoot']) / 'System32'
    env['PATH'] = str(system) + os.pathsep + str(system / 'WindowsPowerShell/v1.0')
    env['PSModulePath'] = str(system / 'WindowsPowerShell/v1.0/Modules')
    ps = system / 'WindowsPowerShell/v1.0/powershell.exe'
    host = folder / 'km003c-overlay-host.exe'
    backup = folder / 'km003c-backup.exe'
    for exe in (host, backup):
        run([exe, '--help'], env)
    verify = [ps, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', folder / 'Install.ps1', '-CheckPackage']
    run(verify, env)
    for language in ('1', '2'):
        run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', folder / 'Install.ps1',
             '-DataDirectory', folder.parent / 'smoke-state'], env, input=language + '\n0\n')
    gate_path = folder / 'overlays/qr/gate.bin'
    original_gate = gate_path.read_bytes()
    try:
        gate_path.write_bytes(bytes([original_gate[0] ^ 1]) + original_gate[1:])
        run(verify, env, good=False)
        out = folder.parent / 'tampered-components-must-not-exist'
        run([host, '--stock', 'missing-stock', 'prepare', '--variant', 'qr', '--overlay', gate_path.parent, '--output', out], env, good=False)
        if out.exists():
            raise RuntimeError('Tampered components created private output')
    finally:
        gate_path.write_bytes(original_gate)
    run(verify, env)
    if stock:
        # Test recovery generation without relying on a pre-existing private container.
        private = folder.parent / 'private-offline-check'
        private.mkdir()
        source = private / 'stock'
        shutil.copytree(stock, source, ignore=shutil.ignore_patterns('stock-restore.mencrypt'))
        run([backup, 'verify', '--stock', source, '--require-dfu'], env)
        for variant in QUALIFIED:
            output = private / variant
            overlays = folder / 'overlays' / variant
            run([host, '--stock', source, 'prepare', '--variant', variant, '--overlay', overlays, '--output', output], env)
            run([host, '--stock', source, 'audit', '--bundle', output / 'bundle'], env)
            expected = overlay207.make_candidate(
                (source / 'stock-app.bin').read_bytes(),
                (source / 'loader-00000004-00003fff.bin').read_bytes(),
                (source / 'internal-tail-00070000.bin').read_bytes(),
                (overlays / 'gate.bin').read_bytes(), (overlays / 'extension.bin').read_bytes())
            for name, raw in zip(('candidate-uncommitted.bin', 'rollback-erase-pass-uncommitted.bin'), expected):
                if (output / 'candidate' / name).read_bytes() != raw:
                    raise RuntimeError('Native preparation differs from qualified Python candidate')
        data_path = source / 'stock-app.bin'
        raw = data_path.read_bytes()
        data_path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        invalid = private / 'bad-stock-must-not-exist'
        run([host, '--stock', source, 'prepare', '--variant', 'qr', '--overlay', folder / 'overlays/qr', '--output', invalid], env, good=False)
        if invalid.exists():
            raise RuntimeError('Invalid backup created output')
    print('Extracted Windows kit: clean-PATH startup, both language menus, integrity/tamper checks passed; no USB accessed.')
    if stock:
        print('Both native candidates equal qualified Python candidates; owner-generated recovery and modeled rollback audited; altered backup refused.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive', type=Path)
    p.add_argument('--extract', type=Path)
    p.add_argument('--smoke-windows', action='store_true')
    p.add_argument('--stock', type=Path, help='Optional PRIVATE qualified backup; offline test only')
    args = p.parse_args()
    contents, manifest = audit(args.archive)
    print(f"Stock-free ZIP inventory passed: {len(contents)} files, version {manifest['project_version']}, commit {manifest['source_commit']}")
    if args.extract:
        args.extract.mkdir(parents=True, exist_ok=False)
        for name, raw in contents.items():
            target = args.extract / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    if args.smoke_windows:
        if os.name != 'nt' or not args.extract:
            p.error('--smoke-windows requires Windows and a NEW --extract folder')
        smoke(args.extract.resolve(), args.stock)
    elif args.stock:
        p.error('--stock is only used with --smoke-windows')


if __name__ == '__main__':
    main()
