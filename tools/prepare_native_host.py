"""Prepare pinned sources and an isolated updater patch; never opens USB.

Use local Git checkouts, or explicitly --fetch public pinned GitHub archives.
Only .deps/native-host is written. Existing prepared output is not overwritten.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'km003c-rs': ('okhsunrog/km003c-rs', 'efed50556d7376914bffd510e012aaa98081936f'),
    'backup': ('inuchanbt/apdo-doom-on-km003c', '20622200644f02c6a5e48ad664dc7b8b6fb236ce'),
}


def edit(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Pinned source patch context mismatch')
    return text.replace(before, after, 1)


def patch_library(folder):
    path = folder / 'km003c-lib/src/firmware.rs'
    original = folder / 'km003c-lib/src/firmware.rs.upstream'
    if not original.exists():
        original.write_bytes(path.read_bytes())
    raw = original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != '8673828441c192397f7d2aa6163e81eecbd7a06606e9a9c711b8bcd0d38bec5a':
        raise ValueError('Unexpected pinned firmware.rs source hash')
    text = raw.decode()
    text = edit(text, 'mod install;', '''mod install;
#[cfg(feature = "hw23-overlay")]
pub mod hw23;

#[derive(Debug, Clone, Copy)]
enum ImageProfile {
    Standard,
    #[cfg(feature = "hw23-overlay")]
    Hw23Overlay,
}
impl ImageProfile {
    fn limit(self) -> usize {
        match self {
            Self::Standard => MAX_IMAGE_BYTES,
            #[cfg(feature = "hw23-overlay")]
            Self::Hw23Overlay => hw23::MAX_BYTES,
        }
    }
}''')
    text = edit(text, '    trailer: Vec<u8>,\n}', '    trailer: Vec<u8>,\n    profile: ImageProfile,\n}')
    text = edit(text, '    pub fn parse(bytes: &[u8]) -> Result<Self, KMError> {', '''    pub fn parse(bytes: &[u8]) -> Result<Self, KMError> {
        Self::parse_profile(bytes, ImageProfile::Standard)
    }

    fn parse_profile(bytes: &[u8], profile: ImageProfile) -> Result<Self, KMError> {''')
    text = edit(text, 'if size == 0 || size > MAX_IMAGE_BYTES {', 'if size == 0 || size > profile.limit() {')
    text = edit(text, '            trailer: trailer.to_vec(),', '            trailer: trailer.to_vec(),\n            profile,')
    text = edit(text, 'self.metadata.size > MAX_IMAGE_BYTES', 'self.metadata.size > self.profile.limit()')
    text = edit(text, '        validate_application_vectors(&self.data)?;', '        validate_application_vectors_with_limit(&self.data, self.profile.limit())?;')
    before = '''        Ok(())
    }

    fn setup_packet'''
    after = '''        #[cfg(feature = "hw23-overlay")]
        if matches!(self.profile, ImageProfile::Hw23Overlay) {
            hw23::validate_payload(&self.data)?;
            hw23::validate_ciphertext(self)?;
        }
        Ok(())
    }

    fn setup_packet'''
    text = edit(text, before, after)
    text = edit(text, '''fn validate_application_vectors(data: &[u8]) -> Result<(), KMError> {
    if !(8..=MAX_IMAGE_BYTES).contains(&data.len()) {''', '''fn validate_application_vectors(data: &[u8]) -> Result<(), KMError> {
    validate_application_vectors_with_limit(data, MAX_IMAGE_BYTES)
}

fn validate_application_vectors_with_limit(data: &[u8], limit: usize) -> Result<(), KMError> {
    if !(8..=limit).contains(&data.len()) {''')
    text = edit(text, '''        transfer_image(self, image, rand::random(), progress).await''', '''        #[cfg(feature = "hw23-overlay")]
        if matches!(image.profile, ImageProfile::Hw23Overlay) {
            hw23::verify_live_loader(self, &identity).await?;
        }
        transfer_image(self, image, rand::random(), progress).await''')
    path.write_text(text, encoding='utf-8', newline='\n')
    cargo = folder / 'km003c-lib/Cargo.toml'
    cargo_original = cargo.with_name('Cargo.toml.upstream')
    if not cargo_original.exists():
        cargo_original.write_bytes(cargo.read_bytes())
    text = edit(cargo_original.read_text(), 'default = []', 'default = []\n# Local exact-build extension profile; standard parsing remains unchanged.\nhw23-overlay = ["dep:sha2"]')
    cargo.write_text(text, encoding='utf-8', newline='\n')
    source = ROOT / 'native-host/library-patch/hw23.rs'
    (folder / 'km003c-lib/src/firmware/hw23.rs').write_bytes(source.read_bytes())
    workspace = folder / 'Cargo.toml'
    workspace_original = workspace.with_name('Cargo.toml.upstream')
    if not workspace_original.exists():
        workspace_original.write_bytes(workspace.read_bytes())
    # Unit-test the library without resolving unrelated GUI workspace members.
    text = edit(workspace_original.read_text(), '''members = [
    "km003c-lib",
    "km003c-cli",
    "km003c-egui",
    "realtime-plot"
]''', 'members = ["km003c-lib"]')
    workspace.write_text(text, encoding='utf-8', newline='\n')
    # Separate pinned workspace lock: the library's own unit tests resolve its
    # optional feature graph, whereas the host lock contains only selected deps.
    library_lock = ROOT / 'native-host/library-patch/Cargo.lock'
    if library_lock.exists():
        (folder / 'Cargo.lock').write_bytes(library_lock.read_bytes())


def patch_backup(folder):
    """Patch the pinned backup crate without changing its original checkout."""
    sources = {
        'lib.rs': 'c65b579fbf2300bf13eeb58d7900a5a4b106c07c891e5d5a031d0f22138eaa4a',
        'main.rs': 'ce846b809847db81fc5ec824e2d87adc1a0fa84357c9e3ff8b16e67e2ff357e0',
    }
    for name, expected in sources.items():
        path = folder / 'bootstrap/src' / name
        original = path.with_name(name + '.upstream')
        if not original.exists():
            original.write_bytes(path.read_bytes())
        raw = original.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Unexpected pinned backup source hash: ' + name)
        text = raw.decode('utf-8')
        if name == 'lib.rs':
            text = edit(text, 'pub const PREFIX: &str = "external-first-3MiB.bin";',
                        'pub const PREFIX: &str = "external-first-3MiB.bin";\nmod external;')
            text = edit(text, '''    let first = reader.read(address, size).await?;
    ensure!(first.len() == size, "short first read: {name}");''', '''    if name == PREFIX {
        return external::acquire_external(reader, dir, name, address, size).await;
    }
    let first = reader.read(address, size).await?;
    ensure!(first.len() == size, "short first read: {name}");''')
            text = edit(text, 'manifest.schema_version == 1\n            && manifest.regions.len() == 5',
                        'matches!(manifest.schema_version, 1 | 2)\n            && manifest.regions.len() == 5')
            text = edit(text, 'if output.len() % 0x40000 == 0 || output.len() == size {',
                        'if size >= 0x10000 && (output.len() % 0x40000 == 0 || output.len() == size) {')
            text = edit(text, '    manifest.identity.supported()?;\n    let app = fs::read(dir.join(APP))?;',
                        '''    manifest.identity.supported()?;
    if manifest.schema_version == 2 {
        external::verify_external_consistency(dir, &manifest.regions[4])?;
    }
    let app = fs::read(dir.join(APP))?;''')
        else:
            text = edit(text, 'schema_version: 1,\n                    identity,',
                        'schema_version: 2,\n                    identity,')
        path.write_text(text, encoding='utf-8', newline='\n')
    (folder / 'bootstrap/src/external.rs').write_bytes((ROOT / 'native-host/backup-patch/external.rs').read_bytes())
    test_path = folder / 'bootstrap/tests/recovery.rs'
    test_original = test_path.with_name('recovery.rs.upstream')
    if not test_original.exists():
        test_original.write_bytes(test_path.read_bytes())
    raw = test_original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != '7ed763a124823ee8f4688d181e7cdba884df747925fec93174c5b0058a7c7e28':
        raise ValueError('Unexpected pinned backup tests hash')
    text = raw.decode('utf-8')
    text = edit(text, 'async fn read(&mut self, _: u32, _: usize) -> Result<Vec<u8>> {',
                'async fn read(&mut self, address: u32, size: usize) -> Result<Vec<u8>> {')
    text = edit(text, '        let mut data = self.data.clone();', '''        let mut data = if self.data.len() == 0x300000 && address >= 0x98000000 {
            let offset = (address - 0x98000000) as usize;
            self.data[offset..offset + size].to_vec()
        } else {
            self.data.clone()
        };''')
    text = edit(text, '        schema_version: 1,\n        identity: Identity {',
                '        schema_version: 2,\n        identity: Identity {')
    test_path.write_text(text, encoding='utf-8', newline='\n')


def extract(name, source, target, fetch):
    repo, revision = PINS[name]
    if source:
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', revision], text=True).strip()
        if actual != revision:
            raise ValueError('Pinned revision not found')
        command = ['git', '-C', str(source), 'archive', revision]
        if name == 'backup':
            command += ['bootstrap', 'LICENSE']
        archive = subprocess.check_output(command)
        strip = False
    elif fetch:
        with urllib.request.urlopen(f'https://codeload.github.com/{repo}/tar.gz/{revision}', timeout=60) as response:
            archive = response.read(64 * 1024 * 1024 + 1)
        strip = True
    else:
        raise ValueError('Supply both local source paths, or explicitly use --fetch')
    if len(archive) > 64 * 1024 * 1024:
        raise ValueError('Unexpected source archive size')
    target.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:*') as tar:
        for member in tar:
            parts = Path(member.name).parts[1:] if strip else Path(member.name).parts
            if not parts:
                continue
            if name == 'backup' and parts[0] not in ('bootstrap', 'LICENSE'):
                continue
            dest = target.joinpath(*parts)
            if not dest.resolve().is_relative_to(target.resolve()):
                raise ValueError('Archive path escapes the prepared dependency')
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as stream:
                    dest.write_bytes(stream.read())
            else:
                raise ValueError('Source archive contains an unsupported special file')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--km003c-source', type=Path)
    parser.add_argument('--backup-source', type=Path)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--refresh-patch', action='store_true', help='Refresh only the isolated local patch from preserved pinned source')
    args = parser.parse_args()
    folder = ROOT / '.deps/native-host'
    if args.refresh_patch:
        report = json.loads((folder / 'prepared.json').read_text())
        if any(report['sources'][name]['revision'] != pin[1] for name, pin in PINS.items()):
            parser.error('Prepared sources do not match pins')
        patch_library(folder / 'km003c-rs')
        patch_backup(folder / 'backup')
        report['patch_sha256'] = hashlib.sha256((ROOT / 'native-host/library-patch/hw23.rs').read_bytes()).hexdigest()
        report['backup_patch_sha256'] = hashlib.sha256((ROOT / 'native-host/backup-patch/external.rs').read_bytes()).hexdigest()
        (folder / 'prepared.json').write_text(json.dumps(report, indent=2) + '\n')
        print('Isolated patch refreshed. No source checkout or USB accessed.')
        return
    if folder.exists():
        parser.error('Prepared directory exists; preserve it and inspect the recorded manifest')
    folder.mkdir(parents=True)
    extract('km003c-rs', args.km003c_source, folder / 'km003c-rs', args.fetch)
    extract('backup', args.backup_source, folder / 'backup', args.fetch)
    patch_library(folder / 'km003c-rs')
    patch_backup(folder / 'backup')
    report = dict(schema=1, sources={name: dict(repository=repo, revision=rev) for name, (repo, rev) in PINS.items()},
                  patch_sha256=hashlib.sha256((ROOT / 'native-host/library-patch/hw23.rs').read_bytes()).hexdigest(),
                  backup_patch_sha256=hashlib.sha256((ROOT / 'native-host/backup-patch/external.rs').read_bytes()).hexdigest(),
                  usb_access=False)
    (folder / 'prepared.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Pinned sources prepared; standard updater limits preserved. No USB accessed.')


if __name__ == '__main__':
    main()
