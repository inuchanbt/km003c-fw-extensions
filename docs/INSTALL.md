# Installation and recovery

[日本語](INSTALL.ja.md)

This initial repository release distributes source only. Build output contains extension components, not an installable stock image. Installation is experimental and requires the exact [HW2.3 / FW2.0.7 profile](COMPATIBILITY.md), an owner's verified backup and qualified loader. Do not use a random internet stock image or a package made for another meter.

1. Keep the original qualified application, loader, calibration and internal-tail backup, with checksums and recovery qualification, privately. The pinned backup tool is prepared by `tools/prepare_native_host.py`; see [native host](../native-host/README.md).
2. Build exactly one variant using `tools/build_firmware.py`. QR and capture are mutually exclusive on the meter.
3. Prepare a private candidate with `python tools/prepare_overlay207.py --stock <qualified-backup> --build <variant-build> --output artifacts/private-candidate`.
4. Package and audit with the qualified native host. Follow its checked DFU/flash/start/readback procedure. Do not bypass the stock, loader, calibration or protected-tail checks.
5. Verify full internal readback and calibration after startup. Store the matching two-stage recovery packages privately before proceeding.

Normal USB reconnect uses no buttons. Holding Exit while reconnecting the side HID port enters the stock bootloader; Exit + OK is also a stock loader shortcut and is not the screenshot shortcut.

For capture, a blank or capture-owned NOR bank is required. Boot does not erase unknown data. The recognized historical DOOM pack can only be reclaimed through the meter's explicit two-stage confirmation; arbitrary data is refused. See [capture controls and partition map](SCREEN-CAPTURE-207.md).

Legacy internal capture bytes at 0x78000–0x7C000 must be exported and explicitly cleared before an update whose guard requires that tail to match the backup. Compatible external capture updates can preserve images after readback/compatibility checks. Before downgrading to a version unaware of the extra bank, export and explicitly clear both banks with the current capture build. Firmware recovery restores internal flash; it does not silently erase external images or restore reclaimed game data.

The public repository cannot supply a prequalified private backup. A future stock firmware version needs a separately tested port, not a renamed image.
