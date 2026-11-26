# KM003C Screen Capture v0.3.2 for Windows

This installer supports qualified KM003C units running stock FW 2.0.7 on HW 2.1 (4 MB ROM) and HW 2.3. An interrupted or failed flash can prevent the meter from booting. Keep a separate copy of your original stock backup and recovery files.

## Before starting

1. On 64-bit Windows 10 or 11, run `Get-FileHash -Algorithm SHA256 "full path to ZIP"` in PowerShell and compare the result with the supplied checksum.
2. Extract the whole ZIP to a new folder and run `Install.cmd`. Close MTools or any other installer. Leave both measurement ports empty and connect only the side USB port. For an existing backup, use the same PC USB port used to make it.
3. Copy any BMPs you want to keep. Disconnect the side USB cable, wait for the screen to go dark, then reconnect while holding only Left and Right. Release both at `USB SCREENSHOTS` and copy the BMPs from the read-only drive. Reconnect with no buttons held to return to normal operation.

## Installer menu

- **1 First install from stock firmware.** Start the unmodified stock firmware normally. Type the displayed serial to create a backup. On HW 2.1, verify 4 MB ROM in Device information or POWER-Z Lab, then type `ROM4MB`. For BOOT Loader, unplug the side USB cable, wait for the screen to go dark, then reconnect while holding only Exit. Release Exit when `BOOT Loader` appears and press Enter. Follow read-only verification and keep a separate copy of the new backup and its session folder before confirming the flash.
- **2 Install or update using an existing backup.** Select the original qualified stock backup folder containing `manifest.json`, or its immediate parent if the folder is named `stock`. Follow the same ROM and BOOT Loader prompts. The installer can identify both variants from Unified Capture v1 using the stock backup. It can also identify earlier supported HW 2.1 capture builds. For another HW 2.3 extension, it asks for the previous `bundle` folder. After the read-only match, type `INSTALL` to update. If v0.3.2 is already installed, the installer skips writing flash and restarts the meter.
- **3 Restore stock firmware.** Use the original backup for that meter. If capture firmware starts, copy out your BMPs, clear the captures with the installed capture firmware, then start the meter normally. Type `CLEARED` to confirm the storage check. If the meter cannot boot, follow the on-screen `DFU` and `EMERGENCY` prompts. This restores internal firmware.
- **4 Identify connected meter.** Displays the hardware revision and USB mode without writing.
- **5 Recover from known HW 2.1 QR remnants.** Use the original backup containing the recognized remnants. The installer requires an exact match before it accepts `CLEAN-QR`. After stock starts and its functions work, use option 2.
- **6 Verify an existing backup and prepare files.** Builds and verifies the files in a new folder without using USB.

If an operation stops, keep the backup and session records private. Review the error before retrying. After a transfer failure, unplug the side USB cable and use the Exit button at the next connection to enter BOOT Loader.

## Capture

On a normal screen, hold Left and Right together for 0.5 to under 2 seconds and release to capture one screen. Hold for at least 2 seconds on a supported screen to capture the full scrollable area. For Themes, open `Application → Settings → Display → Themes`, hold the chord, and wait for `CAPTURE SAVED`. Copy the `THEMES` BMP using the USB steps above. The full list runs from `blue` through `purple`.

The package contains the tools and extension components. The installer generates device-specific files locally using the selected backup. Keep both the backup and generated files private.
