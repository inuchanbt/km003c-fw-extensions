# Changelog

## 0.1.0 - stock FW 2.0.7 profile

- Import the hardware-tested QR implementation from `inuchanbt/km003c-pd-interrogator` commit `ecbeff2`, preserving source/license attribution.
- Add the hardware-tested capture implementation 18c: normal/tall RGB565 BMPs, menu-based names, read-only USB export, 1472 KiB storage and a 96-file catalog.
- Use a shared source tree with separate `qr` and `screen` builds.
- Add bilingual documentation and an exact-stock compatibility profile. No stock firmware, update containers, device backups, calibration data or captures are distributed.
- Preserve the existing QR importer URL for previously generated QR codes. No new Pages deployment is enabled by this repository.
