// Run the prepared backup library's synthetic unit tests in this workspace.
#[allow(dead_code)]
#[path = "../../.deps/native-host/backup/bootstrap/src/lib.rs"]
mod backup;

// Exercise acquisition, manifest verification, DFU qualification and tampering
// against synthetic data through the same patched library used by the binary.
#[path = "../../.deps/native-host/backup/bootstrap/tests/recovery.rs"]
mod upstream_recovery;
