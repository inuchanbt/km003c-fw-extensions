# KM003C FW Extensions

English · [日本語](README.ja.md)

Experimental extensions to the stock ChargerLAB POWER-Z KM003C firmware. This repository maintains **QR display/export** and **screen capture** variants together, with profiles for exact stock firmware builds.

**Current support: stock FW 2.0.7, HW 2.3, exact application and bootloader hashes only.** A matching version label is insufficient. See [compatibility](docs/COMPATIBILITY.md) and the [profile](firmware/v2.0.7/profile.json).

## Choose a variant

| Variant | Features | Meter controls |
| --- | --- | --- |
| `qr` | Export power-source SPR/EPR PDOs, cable e-marker results and PPS status as QR pages; import and decode on a phone | Hold Left + Right about one second; arrows change QR pages, Exit returns |
| `screen` | Lossless 240×240 BMPs or tall scroll-page images; menu name + capture number; read-only USB drive | Hold Left + Right 0.5–under 2 seconds and release for normal capture; hold at least 2 seconds for tall capture |

These are **separate firmware builds**. Keeping both in this repository does not enable both on the meter simultaneously.

Capture storage is **1472 KiB with a 96-file limit**. Large images can fill storage sooner. The 128 MiB USB volume is a virtual BMP view, not physical capacity. See [capture operation](docs/SCREEN-CAPTURE-207.md).

## Install on Windows

Download the **Windows x64 ZIP** from [Releases](https://github.com/inuchanbt/km003c-fw-extensions/releases), extract it, and double-click **Install.cmd**. The English/Japanese menu guides you through your own stock backup, read-only BOOT Loader qualification, QR/capture preparation, installation and restoration. No Python, Rust or compiler is required. The ZIP contains extension components and tools; stock firmware and private recovery are generated locally from your meter. Read [the installation guide](docs/INSTALL.md) first. The kit is experimental and unsigned; see [validation scope](docs/WINDOWS-RELEASE.md).

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

Project version: **0.2.1**. Stock firmware version: **2.0.7**. Release tags include both, e.g. `v0.2.1-fw2.0.7`. Profiles live under `firmware/v<stock-version>/`; future stock versions require their own qualified addresses, hashes and tests. Do not change a version string to reuse a 2.0.7 build on newer firmware.

QR and capture were tested on one qualified HW 2.3 meter. Capture validation includes old-image retention, saving into the additional bank, copying all 48 images through Windows USB and matching readback-derived BMPs, protected-settings CRC and calibration checks. The 96-file catalog was tested on the PC; 96 consecutive physical captures were not performed. See [hardware validation](docs/HARDWARE-SCREEN-2026-11-11.ja.md).

CI runs source-only Python, C/ARM and native-host checks. Private ROM/RAM/device tests require the owner's inputs and are never uploaded. See [contributing and porting](CONTRIBUTING.md).

## License and provenance

Original project code is [MIT](LICENSE). Third-party components retain their own licenses: Nayuki QR generator (MIT), jsQR (Apache-2.0), and separately prepared dependencies. See [third-party notices](THIRD_PARTY_NOTICES.md). Stock firmware and device data are neither included nor relicensed.

The QR implementation originates in [km003c-pd-interrogator](https://github.com/inuchanbt/km003c-pd-interrogator), commit `ecbeff2`. This new repository groups firmware extensions and keeps that attribution. It is an independent project, not an official ChargerLAB release.
