# Windows installation and recovery

[日本語](INSTALL.ja.md)

Download the **Windows x64 ZIP** and its `.sha256` from [GitHub Releases](https://github.com/inuchanbt/km003c-fw-extensions/releases). Use the ZIP asset, rather than GitHub's automatic source archive. This experimental kit supports **KM003C HW 2.3 and the exact stock FW 2.0.7 application/loader hashes** in [the profile](../firmware/v2.0.7/profile.json). Other hardware, firmware builds and premodified units are rejected. QR and capture are separate installations.

## Before starting

Use 64-bit Windows with Windows PowerShell 5.1 (Windows 10/11). No Python, Rust, compiler or network connection is needed after downloading. Extract the entire ZIP to a local folder; do not run it inside the ZIP. Check the download with `Get-FileHash <zip> -Algorithm SHA256` against the supplied checksum. The executables are unsigned; the checksum is an integrity check, not a code signature.

Use one meter only. Leave **both measurement connectors empty** and connect only its side HID port to the PC. Close the ChargerLAB app and other programs using the meter. Keep the same physical PC USB port for backup, BOOT Loader qualification, installation and recovery. This kit does not install or replace USB drivers. If inspection cannot open the device, resolve access/driver issues before proceeding; see the [pinned upstream USB implementation](https://github.com/okhsunrog/km003c-rs/tree/efed50556d7376914bffd510e012aaa98081936f).

Double-click **Install.cmd**, choose English or Japanese, and follow the numbered menu. The launcher checks every listed package file before offering device operations. It does not download firmware or automatically start a transfer.

## First installation: 2 → 3 → 4 → 5

1. **Menu 2: first stock backup.** Boot untouched stock normally, with no buttons held. The tool displays the identity; enter its serial. It reads the application, loader, internal tail and calibration twice as complete regions. The first 3 MiB of external NOR is read in consecutive pairs of 4 KiB chunks; a changing chunk is retried at most twice and must match before it is accepted. This is a non-atomic snapshot: live measurement records may change between chunks. An incomplete or nonmatching backup cannot be used. Private files are stored outside the extracted kit, under `%LOCALAPPDATA%\KM003C-FW-Extensions\`.
2. **Menu 3: recovery-read qualification.** Select that backup. Unplug side HID, hold **Exit only**, reconnect to the **same PC USB port**, and release Exit when BOOT Loader appears. Press Enter. The tool reads the loader and application twice in BOOT Loader and compares them with the stock backup. It makes no flash writes and stays in BOOT Loader. Do not use Exit + OK as a capture shortcut.
3. **Menu 4: prepare offline.** Select QR or capture. The native tool verifies the exact stock/loader hashes, qualified backup, erased internal extension area, and hardcoded hashes of the selected extension components. It derives a private installation bundle and two-stage stock recovery from **your own** backup. No USB access occurs. Copy the complete `stock-*` and `prepared-*` folders to another safe location before installing. A backup must not be substituted with somebody else's files.
4. **Menu 5: install.** Choose the backup and the new `bundle` subfolder. For a first installation, leave the previous-bundle prompt empty. Enter BOOT Loader as instructed and type **INSTALL**. The tool checks the live hardware, physical port, identity where available, exact loader and full internal contents, installs only the bounded extension image, and verifies complete readback. Only after that succeeds does it separately verify and start the extension, then verify application readback/calibration. A failed stage stops the sequence without automatic retries.

Normal reconnection uses **no buttons**. QR: hold Left + Right about one second. Capture: hold Left + Right 0.5–under 2 seconds and release for 240×240, or at least 2 seconds for a supported tall page. See [capture controls](SCREEN-CAPTURE-207.md) and [QR operation](NATIVE-INFO-207.md).

## Replacing an extension

Reuse the original qualified stock backup. Prepare the other variant with menu 4. In menu 5, explicitly supply the **old installed variant's private bundle** when prompted. Both bundles are audited against the same backup, and the live device must exactly match stock, the new extension, or that explicitly supplied old bundle. Unknown firmware is refused. Keep every original/private bundle for recovery.

External capture images can be retained by compatible versions. Export images before switching variants, downgrading or restoring. Legacy internal captures at `0x78000–0x7C000` must be explicitly cleared with their owning build before updating; otherwise protected-tail comparison stops the update. Before downgrading to a version unaware of the extra capture bank, export and explicitly clear **both** banks with the current build.

## Restore or recover

Select the same backup and its prepared `bundle` with **menu 6**. Enter BOOT Loader physically using Exit, then type **RESTORE**. Restoration verifies the loader and protected neighbors, applies and reads back the extension-erasing pass, then applies and reads back your exact original application. Only after successful checks does it start stock. It can resume recognized completed stages; it does not blindly retry uncertain USB transfers.

If a transfer fails or the device state is ambiguous, stop, retain the evidence, unplug side HID and physically re-enter BOOT Loader with Exit before another device command. Do not press other buttons or repeatedly retry a transfer while the loader may be waiting for data. If the tool rejects loader/protected-neighbor bytes or a mismatched backup, preserve all files and investigate rather than bypassing the check. An incomplete `dfu-recovery-check` folder is not qualification; return to normal untouched stock and acquire a fresh backup if initial qualification failed.

Internal firmware recovery does **not** silently erase external captures, restore reclaimed DOOM data, or recover arbitrary external changes. The initial backup covers the first 3 MiB of NOR, not the entire device. Capture firmware never erases an unknown NOR bank at boot; known historical DOOM data requires the meter's explicit two-stage confirmation. See [storage boundaries](SCREEN-CAPTURE-207.md).

## Contents and verification scope

The ZIP contains two stock-free Windows tools, the launcher, separate QR/capture components, English/Japanese instructions, third-party notices and an inventory with per-file SHA-256. It contains **no stock application, loader, update container, calibration, identity or capture images**. Generated `stock-*`, `prepared-*` and operation evidence folders are private; never upload them in bug reports or to GitHub.

The firmware and bounded transfer/recovery implementation have hardware validation on one qualified meter, including restoration and capture installation through the Windows menu. See [Windows release validation](WINDOWS-RELEASE.md) for the exact scope of initial-backup testing.

Developers can still build from [source](../README.md#build-from-source); [native host commands](../native-host/README.md) remain available for diagnostics.
