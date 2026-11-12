# Development and ports

## Source-only checks

```sh
python -m pip install -r requirements.txt unicorn==2.1.4
python -m unittest discover -s tests -v
python tools/build_firmware.py --stock-fw 2.0.7 --variant qr --clang clang
python tools/check_overlay207.py artifacts/fw2.0.7/qr
python tools/build_firmware.py --stock-fw 2.0.7 --variant screen --clang clang
python tools/check_overlay207.py artifacts/fw2.0.7/screen
node --check phone/app.js
node --check phone/codec.js
node --check phone/store.js
```

The QR/private stock analysis uses its documented environment. Private native screen replay specifically requires a separate `unicorn==2.1.3` environment; see `tools/check_screen207.py`. CI does not require ROM/RAM snapshots or a USB device.

Prepare native-host dependencies with `python tools/prepare_native_host.py --fetch`, then use `cargo test --manifest-path native-host/Cargo.toml --locked`. Prepared source is isolated under ignored `.deps/`; upstream commits are pinned. Keep vendor license files intact.

## New stock versions

Follow [compatibility and porting](docs/COMPATIBILITY.md). Keep old firmware profiles reproducible. Never relax exact-build checks to accept an unqualified firmware or hardware revision. Record tested versus modeled behavior separately.

## Publication

Only source, synthetic fixtures, license files and sanitized documentation belong in Git. Backups, calibration, serial/device identity, raw stock/disassembly/RAM/NOR, BMP captures and generated private update packages stay outside commits, Actions uploads and releases. Do not use `git add -f` for these files. Windows Releases may contain only audited stock-free tools/components and their notices, assembled with the fixed packager; see [release validation](docs/WINDOWS-RELEASE.md). Never upload a private preparation or backup folder.

日本語: FW別の移植条件は[対応表](docs/COMPATIBILITY.ja.md)を参照してください。個体情報や純正ROMを含まない公開ソースだけで試験できることを維持し、実機確認とモデル試験を区別してください。
