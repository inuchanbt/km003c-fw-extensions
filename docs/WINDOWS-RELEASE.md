# Windows release assembly and validation

Project **0.2.0**, stock profile **FW 2.0.7 / HW 2.3**. [English installation](INSTALL.md) / [日本語の導入手順](INSTALL.ja.md).

The firmware components are unchanged: QR 13400 bytes (`4140de1a…`) and capture 15516 bytes (`d2687c4f…`), with the exact full reference hashes in [the profile](../firmware/v2.0.7/profile.json). The Windows native tool also pins the gate hashes. A mismatched component/variant stops before stock processing or USB access.

## Build and assemble

Prepare the pinned dependencies with `python tools/prepare_native_host.py --fetch`. Build the native host and pinned backup CLI together using Rust **1.99.1**, `cargo build --manifest-path native-host/Cargo.toml --release --bins --locked`. The distributed x64 GNU build uses LLVM-MinGW **20261020**, LLD, stripped release binaries and source-path remapping. The source supports the additional Windows MSVC CI build; CI does not upload private evidence or automatically publish a release.

Build both variants with `tools/build_firmware.py` and the qualified compiler. Export `cargo metadata --manifest-path native-host/Cargo.toml --format-version 1 --locked --filter-platform x86_64-pc-windows-gnu` to a private/ignored build file. It is a packager input, never a release asset. Include Rust library copyright/license texts, the MinGW runtime notices and LLVM's license from the toolchain. The metadata supplies resolved crate licenses; upstream licenses are preserved.

```sh
python tools/package_windows_release.py --executables <release-bin-dir> \
  --qr artifacts/fw2.0.7/qr --screen artifacts/fw2.0.7/screen \
  --metadata <cargo-metadata.json> --runtime-license <license-file> \
  --source-commit <full-40-character-commit> --output artifacts/release
```

Repeat `--runtime-license` for each required runtime/copyright text. `--metadata` can also be repeated. Packaging requires Git and a clean committed public source tree whose HEAD matches `--source-commit`. The fixed packager refuses components outside the two qualified reference builds. Its ZIP includes two executables, the PowerShell/cmd launcher, both component sets, committed public sources (including vendor notices), documentation, notices and a per-file release manifest. It adds a UTF-8 BOM to the distributed PowerShell script for Windows PowerShell 5.1. A separate `.zip.sha256` is generated. No `.deps` or owner `artifacts` directory is copied into the ZIP.

## Checks required before publishing

- Run Python/C source checks, native-host tests, and patched-library firmware tests. These include component rejection before output creation, patch boundaries, ordinary-parser bounds, uncertain-transfer behavior, full modeled recovery and stock-container roundtrip. CI runs Linux and Windows checks.
- Use `python tools/check_windows_release.py <zip>` to verify the ZIP checksum, complete inventory, path safety, exact component hashes and exclusion of private/unsupported binary files.
- On Windows, add `--extract <NEW-folder> --smoke-windows`. It launches both executables and both language menus with a clean system-only PATH, checks the package in Windows PowerShell 5.1, modifies a component to ensure rejection, and restores it. No USB is opened.
- For private offline qualification, also pass `--stock <your-qualified-backup>`. This creates a private copy **without** a pre-existing restore container, verifies qualification, prepares and audits both variants, compares both entire candidates/erase passes against the earlier Python implementation, and rejects an altered backup. These files stay ignored and are never release inputs.
- Inspect binary DLL imports and scan the final ZIP for workstation paths, device serials and stock/loader/calibration payloads. Publish only the ZIP and its checksum. Download the published ZIP again and verify the checksum.

The release validates the new launcher/preparation path **offline**; it does not claim a fresh physical installation through that menu. The underlying QR/capture firmware and transfer/recovery paths have earlier hardware results on one qualified meter. The 96-image catalog is PC-tested, not a 96-capture physical endurance test. Executables are unsigned. Firmware version text alone does not establish compatibility.

日本語：今回のWindows版は、純正FWを含めない配布用キットです。新しいメニューからの実機書込みを今回再実施したとは扱わず、オフラインでの生成・復旧照合・改変拒否・展開後の起動確認と、従来の実機確認を区別します。個体バックアップや生成された更新／復旧データをZIPやGitHubへ混ぜないでください。
