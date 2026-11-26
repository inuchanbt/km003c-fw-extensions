# KM003C FW Extensions

English · [日本語](README.ja.md)

Experimental extensions to the stock ChargerLAB POWER-Z KM003C firmware. This repository maintains **QR display/export** and **screen capture** variants together, with profiles for exact stock firmware builds.

**Stock FW 2.0.7 only.** Screen Capture supports qualified HW 2.1 (4 MB ROM) and HW 2.3. QR supports qualified HW 2.3. See [compatibility](docs/COMPATIBILITY.md) for the exact build requirements.

## Choose a variant

| Variant | Features | Meter controls |
| --- | --- | --- |
| `qr` | Export power-source SPR/EPR PDOs, cable e-marker results and PPS status as QR pages; import and decode on a phone | Hold Left + Right about one second; arrows change QR pages, Exit returns |
| `screen` | Lossless 240×240 BMPs or tall scroll-page images; boot number + menu + capture number; read-only USB drive | Hold Left + Right 0.5–under 2 seconds and release for normal capture; hold at least 2 seconds for tall capture |

These are **separate firmware builds**. Keeping both in this repository does not enable both on the meter simultaneously.

Capture storage on HW 2.3 is **1472 KiB with a 96-file limit**. HW 2.1 uses **1 MiB with a 64-file limit**. Large images can fill storage sooner. The 128 MiB USB volume presents the captured BMPs. See [capture operation](docs/SCREEN-CAPTURE-207.md).

New captures group by boot, for example `0001_MEASUREMENT02.BMP`. Old captures keep their names. Export and clear captures with the installed capture firmware before downgrading or restoring stock.

## Install on Windows

- **Screen Capture (HW 2.1 and 2.3).** Extract the Windows x64 ZIP and run `Install.cmd`. For upgrades from Unified Capture v1, choose option 2 and select the original stock backup. The installer displays English prompts and includes English and Japanese instructions. [Download v0.3.2](https://github.com/inuchanbt/km003c-fw-extensions/releases/tag/v0.3.2-fw2.0.7) · [Installation guide](docs/INSTALL-CAPTURE.md)
- **QR (HW 2.3).** Use the earlier Windows kit and its English/Japanese installer. [Download v0.3.1](https://github.com/inuchanbt/km003c-fw-extensions/releases/tag/v0.3.1-fw2.0.7) · [Installation guide](docs/INSTALL.md)

Both kits generate private installation and recovery files locally from your meter's stock backup. The installers are unsigned.

## Build from source

Requires Python 3.12+, Clang/LLD with `arm-none-eabi` support and Node.js for the phone tests. Rust is required only for the native host tools.

```sh
python -m pip install -r requirements.txt
python tools/build_firmware.py --stock-fw 2.0.7 --variant qr --clang clang
python tools/build_firmware.py --stock-fw 2.0.7 --variant screen --clang clang
```

PowerShell shortcut: `./Build.ps1 -Variant screen -Clang C:\tools\clang.exe`.

Outputs go to ignored `artifacts/fw2.0.7/<variant>/`. They are **stock-free overlay components, not ready-to-flash firmware**. Installation requires an exact verified backup from the owner's meter and the qualified updater. Read [installation/recovery](docs/INSTALL.md) before any device operation. No build or test command above opens USB.

## Use the QR importer

[Open the compatible phone importer](https://inuchanbt.github.io/km003c-pd-interrogator/). It decodes QR data locally in the browser and also includes clearly marked synthetic demos. This URL is intentionally retained for compatibility with the hardware-tested QR build; the importer source is in `phone/`.

```sh
python -m pdinfo demo --output artifacts/demo --qr
python -m pdinfo serve
```

See [QR operation and queries](docs/NATIVE-INFO-207.md) and [the host CLI](docs/HOST-CLI.md).

## Firmware versions and validation

Screen Capture **v0.3.2** targets stock firmware **2.0.7**. The Themes list was captured through `purple` on both hardware revisions. On HW 2.3, the resulting BMP was 240×296 and was copied from the USB drive. On HW 2.1, [@tomoca2](https://github.com/tomoca2) reported a successful update, tall capture and recovery with the trial build.

On one qualified HW 2.3 meter, the 0.3.1 capture component exported 240×305 Auto detection BMPs with and without a PD 3.1 dialog. The dialog and firmware version each appeared once. Earlier validation covered capture filenames grouped by boot, 48 USB image copies and the extra storage bank. The Windows ZIP is checked offline. See [hardware validation](docs/SCREEN-CAPTURE-BOOT-NUMBER.ja.md).

CI runs source-only Python, C/ARM and native-host checks. Private ROM/RAM/device tests require the owner's inputs and are never uploaded. See [contributing and porting](CONTRIBUTING.md).

## License and provenance

Original project code is [MIT](LICENSE). Third-party components retain their own licenses: Nayuki QR generator (MIT), jsQR (Apache-2.0), and separately prepared dependencies. See [third-party notices](THIRD_PARTY_NOTICES.md). Stock firmware and device data are neither included nor relicensed.

The QR implementation originates in [km003c-pd-interrogator](https://github.com/inuchanbt/km003c-pd-interrogator), commit `ecbeff2`. This new repository groups firmware extensions and keeps that attribution. It is an independent project, not an official ChargerLAB release.
