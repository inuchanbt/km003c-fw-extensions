# Compatibility and versioning

[日本語](COMPATIBILITY.ja.md)

| Stock firmware | Hardware | QR | Screen capture |
| --- | --- | --- | --- |
| 2.0.7, exact qualified hashes | 2.1 (4 MB ROM) | Unsupported in the current release | Screen Capture v0.3.2, trial update and tall capture confirmed on one meter |
| 2.0.7, exact profile hashes | 2.3 | Hardware tested on one meter | Screen Capture v0.3.2, tall capture and USB export confirmed on one meter |
| Any other version/build or hardware | Any | Unsupported | Unsupported |

The application and loader hashes for HW 2.3 are in [the profile](../firmware/v2.0.7/profile.json). The HW 2.1 backend carries its own loader check in [the library patch](../hw21-trial-source/native-host/library-patch/hw23.rs). Device identity and backup checks run locally in the updater.

The general-purpose kit uses SemVer from `VERSION`. The unified capture installer specifies its own release version in [its packager](../tools/package_capture_trial.py). Both use tags such as `v0.3.2-fw2.0.7` to identify the release and its stock firmware target. Record the variant, stock profile, compiler and test status in release notes. Reference extension hashes identify compiler-specific builds.

For a new stock version, add a profile directory and a dedicated implementation/build route. Requalify loader/application hashes, RAM ownership, GUI/input/display APIs, USB ABI, flash erase/program bounds and recovery. Preserve existing profiles and fail closed on unknown versions. `tools/build_firmware.py` explicitly routes supported implementations; a profile JSON alone does not enable a new version.

No private stock application, loader, update package, identity, calibration or capture belongs in commits, CI artifacts or releases. Windows kits contain only tools and stock-free extension components; they derive private installation/recovery files from each owner's qualified backup. See [installation](INSTALL.md).
