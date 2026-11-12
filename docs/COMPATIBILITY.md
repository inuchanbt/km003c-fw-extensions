# Compatibility and versioning

[日本語](COMPATIBILITY.ja.md)

| Stock firmware | Hardware | QR | Screen capture |
| --- | --- | --- | --- |
| 2.0.7, exact profile hashes | 2.3 | Hardware tested on one meter | Implementation 18c, hardware tested on one meter |
| Any other version/build or hardware | Any | Unsupported | Unsupported |

The application SHA-256 and qualified loader SHA-256 are in [the profile](../firmware/v2.0.7/profile.json). Device identity, owner backups and calibration are checked privately by the updater. A shared version label does not establish compatibility.

Project releases use SemVer from `VERSION`, independently of the stock version. Use annotated tags such as `v0.1.0-fw2.0.7`. Record the variant, stock profile, compiler and test status in release notes. Compiler-specific reference extension hashes describe the hardware-tested local builds; other compiler outputs must not be advertised as bit-identical without comparison.

For a new stock version, add a profile directory and a dedicated implementation/build route. Requalify loader/application hashes, RAM ownership, GUI/input/display APIs, USB ABI, flash erase/program bounds and recovery. Preserve existing profiles and fail closed on unknown versions. `tools/build_firmware.py` explicitly routes supported implementations; a profile JSON alone does not enable a new version.

No private stock application, loader, update package, identity, calibration or capture belongs in commits, CI artifacts or releases. Windows kits contain only tools and stock-free extension components; they derive private installation/recovery files from each owner's qualified backup. See [installation](INSTALL.md).
