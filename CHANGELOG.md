# Changelog

## 0.3.1 - Keep tall Auto detection captures intact

- Draw the result dialog once in its original position and the firmware version once at the bottom. Keep the full scrollable content and boot-grouped filenames.
- On one HW 2.3 / FW 2.0.7 meter, updated and read back the capture component, then exported 240×305 BMPs with and without a PD 3.1 result dialog. The dialog and version each appear once, and the dialog-free image matches the preceding build pixel for pixel.
- The capture format is compatible with 0.3.0, and a direct update uses the same stock backup and the previous private bundle. The QR component is unchanged.

## 0.3.0 - Capture filenames grouped by boot

- Prefix newly saved screenshots with a minimum-four-digit boot group, such as `0001_MEASUREMENT02.BMP`; images saved during the same boot share a group. Existing images keep their names and contents.
- Allocate a group on the first successful save, not on export-only or capture-free boots. Clearing all captures resets numbering; the number is not a permanent identifier.
- Store the new group in CRC-protected KSN2 records; old capture firmware cannot read them. Export images and clear both capture banks with this version before downgrading or restoring stock.
- A predecessor was tested on one HW 2.3 / FW 2.0.7 meter across three capture boots including a tall Modules screenshot. The final component was installed on that meter and exported a further grouped capture with prior images retained; its missing-title branch was PC-tested. The packaged Windows installer was verified offline, not installed end-to-end on a second meter. HW 2.1 remains unsupported.

## 0.2.1 - Live external-memory backup

- Read the first 3 MiB of external NOR as consecutive verified 4 KiB pairs, retrying a changing chunk at most twice. The resulting snapshot is explicitly non-atomic and its method is recorded in schema 2; old schema 1 backups remain readable.
- Full-region double reads and strict matching remain required for the application, loader, internal tail and calibration. An unstable or short external chunk stops backup without a success record.
- Keep firmware components and bounded installation/recovery behavior unchanged.

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
