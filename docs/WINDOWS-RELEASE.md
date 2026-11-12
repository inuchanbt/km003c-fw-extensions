# Windows release assembly and validation

Project **0.2.1**, stock profile **FW 2.0.7 / HW 2.3**. [English installation](INSTALL.md) / [日本語の導入手順](INSTALL.ja.md).

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

On one qualified HW 2.3 meter, version 0.2.0's menu restored stock and installed capture using an earlier qualified backup; internal readback, calibration, capture and USB export passed. Its first-backup attempt failed because two full reads of live external NOR differed. Subsequent read-only observations found 26 changed bytes in the native-record region while the first MiB matched; this reproduces the type of mismatch, though the discarded second read from the original failure prevents proving it was the exact same change.

For 0.2.1, a read-only probe matched all 768 consecutive 4 KiB pairs. The corrected native backup tool then acquired a fresh stock backup on the meter, qualified loader/application reads in DFU, generated an installation and recovery bundle from that new backup, installed the capture variant, and verified the full internal readback and calibration. The meter displayed `CAPTURE SAVED`. This hardware run used the corrected native CLI, not a freshly downloaded 0.2.1 ZIP; the extracted Windows menu and package are separately smoke-tested offline. The external backup is non-atomic, even if every chunk pair matches. The 96-image catalog is PC-tested, not a 96-capture physical endurance test. Executables are unsigned. Firmware version text alone does not establish compatibility.

日本語：純正FWを含めない配布用キットです。0.2.1の修正版CLIで、純正からの新規バックアップ・DFU読取照合・導入用データの生成・キャプチャ版書込み・撮影を実機1台で確認しました。0.2.1の完成ZIPを使った新規の実機導入と、オフラインでの展開・起動・改変拒否は区別します。外部メモリーのバックアップは区画ごとに2回照合しますが、全体は非原子的です。個体バックアップや生成された更新／復旧データをZIPやGitHubへ混ぜないでください。
