# Screen capture — stock FW 2.0.7 / HW 2.3

[日本語](SCREEN-CAPTURE-207.ja.md)

The `screen` variant replaces QR display with lossless capture of the native GUI. The current implementation is 18c; project release versions are separate.

## Controls

1. On the desired screen, hold Left + Right for 0.5 to less than 2 seconds and release for a visible 240×240 capture. Hold for at least 2 seconds for a tall capture. Wait for CAPTURE SAVED before removing power. A held chord captures once.
2. Disconnect the measurement connectors. Hold Left + Right only while reconnecting the side HID USB port to the PC. Release after USB SCREENSHOTS appears. Copy BMPs from the read-only KM003C drive.
3. Reconnect without buttons to resume the native measurement screen.

Exit + OK is a stock bootloader shortcut, not capture. Individual arrow presses can be delayed up to 150 ms to distinguish the chord. Native raw-button readers and the GUI reader both suppress the capture chord, while preserving watchdog refresh.

Tall capture supports full-width native window pages up to 240×2048. The header appears once; the original scroll position and scrollbar state are restored. Non-overflowing pages stay 240×240. Unsupported overflowing pages report LONG CAPTURE UNAVAILABLE. Dynamic content must match across both redraw passes; otherwise the reservation is not committed and DISPLAY CHANGED / RETRY is shown.

## Files and capacity

New files use uppercase ASCII menu names plus a minimum-two-digit shared sequence, e.g. USBCEMARKER41.BMP or CAPACITY48.BMP. Spaces/punctuation are omitted; unidentified screens use SCREEN. Existing unnamed records retain SC000001.BMP. Numbers expand rather than truncate if necessary. File dates are fixed FAT metadata, not capture timestamps.

Physical capture storage is **1472 KiB**, with a **96-file catalog limit**. A 16 KiB reservation per image allows 92 images in an otherwise empty bank layout; small records can share sectors. Large tall images and interrupted reservations consume more space, so 96 files are not guaranteed. Full storage does not overwrite old files.

The **128 MiB FAT16 volume is virtual**: it expands immutable compressed RGB565 records to top-down BMPs. It does not represent physical capture capacity. Windows writes, formatting and deletion are rejected as write-protected.

| External NOR region | Purpose |
| --- | --- |
| 0x000000–0x100000 | Original 1 MiB capture bank, reclaimed from the recognized historical game assets on the test meter |
| 0x100000–0x300000 | Native measurement records; preserved |
| 0x300000–0x380000 | Native update staging; preserved |
| 0x380000–0x3F0000 | Additional 448 KiB capture bank |
| 0x3F0000–0x400000 | Entire final 64 KiB reserved as a settings guard |

The meter checks the extra bank's blank/ownership status and CRC at boot. Foreign contents disable that bank; the original bank remains usable. Captures prefer the extra bank, then fall back to the original bank. No capture automatically erases. Ownership markers, length/sequence complements, CRC, readback and a final commit protect append publication. Native bus arbitration and page-bounded native program commands are reused. New storage must not be inferred from a different firmware's partition layout.

The 96-entry ARM catalog uses the same 776 bytes as the previous 64-entry catalog: immutable sequence numbers are read from journal headers instead of duplicated in RAM. No full framebuffer or whole compressed-image buffer is allocated. Encoding uses two matching redraws and a 256-byte streaming page buffer.

## Clear and firmware changes

Back up wanted files first. On USB SCREENSHOTS, hold OK alone for two seconds. After ERASE ALL CAPTURES? appears, release all buttons and hold OK alone for another two seconds. Exit cancels. Both enabled banks are preflighted before erase; unknown contents are never formatted. Reconnect normally after completion.

The specifically recognized old DOOM pack uses ERASE DOOM DATA? followed by a separate two-second OK confirmation. This is an explicit destructive operation on that recognized pack; boot alone does not reclaim it. Arbitrary data is refused.

Compatible capture updates may preserve external records after full readback/compatibility checks. Export and explicitly clear both banks before downgrading to a version that cannot see the extra bank. Legacy internal captures require the updater's protected-tail checks; see [installation/recovery](INSTALL.md).

## Validation and build

[Hardware record](HARDWARE-SCREEN-2026-11-11.ja.md): one qualified meter, original 47-image bank byte-identical after update, real capture into the new bank, all 48 Windows USB BMPs matching readback-derived images, extra-bank/settings-guard CRC retention and calibration/internal readback checks after normal return. Ninety-six files, final-slot BMPs, torn writes and range guards were tested on the PC; 96 consecutive physical captures and exhaustive physical power-loss cases were not performed.

```sh
python tools/build_firmware.py --stock-fw 2.0.7 --variant screen --clang clang
python tools/check_overlay207.py artifacts/fw2.0.7/screen
python -m unittest tests.test_screen -v
```

Private native ROM/RAM replay is optional and never opens USB. It requires the owner's inputs and a separate unicorn==2.1.3 environment; see tools/check_screen207.py. No private inputs are distributed.
