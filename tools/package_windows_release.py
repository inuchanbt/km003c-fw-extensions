"""Package a fixed, stock-free Windows kit. Never reads owner backups or USB."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILES = (
    'LICENSE', 'THIRD_PARTY_NOTICES.md', 'VERSION', 'README.md', 'README.ja.md',
    'firmware/README.md', 'firmware/v2.0.7/profile.json', 'CONTRIBUTING.md',
    'native-host/README.md', 'native-host/README.ja.md',
)
QUALIFIED = {
    'qr': ('ffc18d85c1cbccad49dc597cb44894597176129cb0821f4bbd5d0183f521d556',
           '4140de1a80beef119b18de0f12bc0ebbcfe74c2c579bb24941694173ee4e25f0'),
    'screen': ('0d8089b74a0dca4fed1e16e19bb356745943ab9efced926a2c4c1dc109a127ee',
               'd2687c4fc7b27d55ab934d2dda74d9b6a7830254d786f78cd7f3bdc3b4c4778b'),
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dependency_notices(metadata_files):
    files, inventory = {}, {}
    for metadata in metadata_files:
        for package in json.loads(metadata.read_text(encoding='utf-8-sig'))['packages']:
            folder = Path(package['manifest_path']).parent
            name = f"{package['name']}-{package['version']}"
            inventory[name] = package['license'] or 'See included notices'
            for item in folder.iterdir():
                if item.is_file() and item.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'COPYRIGHT', 'NOTICE')):
                    files[f'licenses/{name}/{item.name}'] = item
            if package['license_file']:
                item = folder / package['license_file']
                files[f'licenses/{name}/{item.name}'] = item
    return files, inventory


def overlay_files(folder, variant):
    gate = (folder / 'gate.bin').read_bytes()
    extension = (folder / 'extension.bin').read_bytes()
    report = json.loads((folder / 'build.json').read_text(encoding='utf-8'))
    if ((digest(gate), digest(extension)) != QUALIFIED[variant]
            or len(gate) != report['gate_bytes'] or len(extension) != report['extension_bytes']
            or digest(extension) != report['extension_sha256'] or report['variant'] != variant):
        raise ValueError('Components do not match the hardware-qualified ' + variant + ' build')
    return {f'overlays/{variant}/{name}': folder / name for name in ('gate.bin', 'extension.bin', 'build.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executables', type=Path, required=True)
    parser.add_argument('--qr', type=Path, required=True)
    parser.add_argument('--screen', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True, action='append')
    parser.add_argument('--runtime-license', type=Path, required=True, action='append')
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.source_commit):
        parser.error('Source commit must be a full Git commit SHA')
    version = (ROOT / 'VERSION').read_text(encoding='ascii').strip()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if args.source_commit != head or subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=ROOT).returncode:
        parser.error('Package only from the specified, clean committed source tree')
    archive_name = f'km003c-fw-extensions-v{version}-fw2.0.7-windows-x64.zip'
    files = {name: ROOT / name for name in PROJECT_FILES}
    # Include only committed public sources, keeping documentation links and
    # vendored license notices usable offline. Never recurse into local targets.
    tracked = subprocess.check_output(['git', 'ls-files', '--', 'native', 'native-host', 'pdinfo',
                                      'phone', 'tools', 'tests', 'firmware', 'windows'], cwd=ROOT, text=True)
    for name in tracked.splitlines():
        if any(part in ('.deps', 'artifacts', 'target', '__pycache__') for part in Path(name).parts):
            raise ValueError('Private/build directory must not be tracked')
        if Path(name).suffix.lower() in ('.bin', '.bmp', '.exe', '.dll', '.mencrypt', '.elf'):
            raise ValueError('Only public source files may enter the source portion')
        files[name] = ROOT / name
    for name in ('Build.ps1', 'pdinfo.ps1', 'requirements.txt', 'requirements-dev.txt', 'CHANGELOG.md', '.gitignore', '.gitattributes'):
        files[name] = ROOT / name
    for item in (ROOT / 'docs').glob('*.md'):
        files[item.relative_to(ROOT).as_posix()] = item
    files['docs/images/demo-en.png'] = ROOT / 'docs/images/demo-en.png'
    for name in ('Install.cmd', 'Install.ps1'):
        files[name] = ROOT / 'windows' / name
    for name in ('km003c-overlay-host.exe', 'km003c-backup.exe'):
        path = args.executables / name
        if not path.read_bytes().startswith(b'MZ'):
            parser.error('Missing Windows executable: ' + name)
        files[name] = path
    files.update(overlay_files(args.qr, 'qr'))
    files.update(overlay_files(args.screen, 'screen'))
    files['licenses/km003c-backup-0.1.0/LICENSE'] = ROOT / '.deps/native-host/backup/LICENSE'
    for name in ('LICENSE-APACHE', 'LICENSE-MIT'):
        files[f'licenses/km003c-rs/{name}'] = ROOT / '.deps/native-host/km003c-rs' / name
    notices, inventory = dependency_notices(args.metadata)
    files.update(notices)
    for index, source in enumerate(args.runtime_license, 1):
        files[f'licenses/toolchain/{index}-{source.name}'] = source
    contents = {name: source.read_bytes() for name, source in files.items()}
    # Windows PowerShell 5.1 requires a BOM for non-ASCII source text.
    contents['Install.ps1'] = b'\xef\xbb\xbf' + contents['Install.ps1'].removeprefix(b'\xef\xbb\xbf')
    contents['licenses/cargo-inventory.json'] = (json.dumps(inventory, indent=2, sort_keys=True) + '\n').encode()
    contents['START-HERE.md'] = (
        '# KM003C FW Extensions for Windows\n\n'
        'Extract the entire ZIP, then double-click **Install.cmd**. Choose English or Japanese.\n\n'
        '**HW 2.3 / exact stock FW 2.0.7 only.** Start with menu 2 (your own stock backup), '
        '3 (read-only bootloader qualification), 4 (prepare QR or capture), then 5 (install). '
        'Menu 6 restores stock. Keep the backup and prepared recovery folders privately.\n\n'
        '[English instructions](docs/INSTALL.md) / [Japanese instructions](docs/INSTALL.ja.md)\n\n'
        'No Python, Rust or compiler is needed. No stock firmware or owner data is included.\n'
    ).encode('utf-8')
    manifest = dict(schema=1, project_version=version, stock_firmware='2.0.7', hardware='2.3',
                    source_commit=args.source_commit, stock_free=True, installable_firmware_included=False,
                    files=[dict(path=name, bytes=len(raw), sha256=digest(raw)) for name, raw in sorted(contents.items())])
    contents['release-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / archive_name
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED, compresslevel=9) as zip_file:
        for name, raw in sorted(contents.items()):
            zip_file.writestr(name, raw)
    archive.with_suffix('.zip.sha256').write_text(f'{digest(archive.read_bytes())}  {archive.name}\n', encoding='ascii')
    print(archive)


if __name__ == '__main__':
    main()
