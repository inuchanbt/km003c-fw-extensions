# Changelog

## 0.2.0 - Windows stock-free installation kit, stock FW 2.0.7

- Add an English/Japanese Windows menu for first backup, read-only loader qualification, offline variant preparation, explicit installation and two-stage restoration.
- Distribute the native host and pinned backup CLI with separate, unchanged hardware-qualified QR/capture components. No Python/compiler or bundled stock firmware is required.
- Derive an exact original recovery container from the owner's qualified backup when absent, retaining full roundtrip and bounded-flash checks.
- Add per-file and ZIP SHA-256, dependency/runtime notices, extracted-kit offline checks and Windows CI.
- Firmware behavior and reference component hashes are unchanged from 0.1.0. The new menu is offline-tested; a new physical installation through it has not been performed.

## 0.1.0 - stock FW 2.0.7 profile

- Import the hardware-tested QR implementation from `inuchanbt/km003c-pd-interrogator` commit `ecbeff2`, preserving source/license attribution.
- Add the hardware-tested capture implementation 18c: normal/tall RGB565 BMPs, menu-based names, read-only USB export, 1472 KiB storage and a 96-file catalog.
- Use a shared source tree with separate `qr` and `screen` builds.
- Add bilingual documentation and an exact-stock compatibility profile. No stock firmware, update containers, device backups, calibration data or captures are distributed.
- Preserve the existing QR importer URL for previously generated QR codes. No new Pages deployment is enabled by this repository.
