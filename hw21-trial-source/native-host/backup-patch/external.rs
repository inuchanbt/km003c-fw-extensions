// SPDX-License-Identifier: MIT
//! A live log can change between full passes. Each accepted chunk is read twice
//! consecutively; the complete result remains a non-atomic snapshot.
use super::*;

const CHUNK: usize = 4096;
const MAX_ATTEMPTS: usize = 3;

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ExternalConsistency {
    schema: u8,
    method: String,
    chunk_bytes: usize,
    chunks: usize,
    retries: usize,
    bytes: usize,
    sha256: String,
    atomic: bool,
}

pub(super) async fn acquire_external(
    reader: &mut impl ReadMemory,
    dir: &Path,
    name: &str,
    address: u32,
    size: usize,
) -> Result<Region> {
    ensure!(
        name == PREFIX && address == 0x98000000 && size == 0x300000,
        "unsupported external backup range"
    );
    ensure!(!dir.join(name).exists(), "output already exists");
    let mut data = Vec::with_capacity(size);
    let mut retries = 0;
    for offset in (0..size).step_by(CHUNK) {
        let at = address
            .checked_add(offset.try_into()?)
            .context("external offset overflow")?;
        let mut accepted = None;
        for attempt in 0..MAX_ATTEMPTS {
            let first = reader.read(at, CHUNK).await?;
            let second = reader.read(at, CHUNK).await?;
            ensure!(
                first.len() == CHUNK && second.len() == CHUNK,
                "short external read at {at:#x}"
            );
            if first == second {
                accepted = Some(first);
                break;
            }
            if attempt + 1 < MAX_ATTEMPTS {
                retries += 1;
            }
        }
        data.extend(accepted.with_context(|| {
            format!("external chunk at {at:#x} changed repeatedly; backup incomplete")
        })?);
        if data.len().is_multiple_of(0x40000) || data.len() == size {
            println!("External backup verified: {}/{} bytes", data.len(), size);
        }
    }
    let entry = Region {
        file: name.into(),
        address,
        bytes: size,
        sha256: digest(&data),
        matching_reads: 2,
    };
    let consistency = ExternalConsistency {
        schema: 1,
        method: "consecutive_chunk_pairs".into(),
        chunk_bytes: CHUNK,
        chunks: size / CHUNK,
        retries,
        bytes: size,
        sha256: entry.sha256.clone(),
        atomic: false,
    };
    save(&dir.join(name), &data)?;
    save(
        &dir.join(format!("{name}.sha256")),
        format!("{}  {name}\n", entry.sha256).as_bytes(),
    )?;
    save_json(&dir.join(format!("{name}.verified.json")), &entry)?;
    save_json(&dir.join(format!("{name}.consistency.json")), &consistency)?;
    println!(
        "External backup: {} consecutive chunk pairs matched; {} retries. Snapshot is not atomic.",
        consistency.chunks, retries
    );
    Ok(entry)
}

pub(super) fn verify_external_consistency(dir: &Path, entry: &Region) -> Result<()> {
    let report: ExternalConsistency =
        serde_json::from_slice(&fs::read(dir.join(format!("{PREFIX}.consistency.json")))?)?;
    ensure!(
        report.schema == 1
            && report.method == "consecutive_chunk_pairs"
            && report.chunk_bytes == CHUNK
            && report.bytes == 0x300000
            && report.chunks == report.bytes / CHUNK
            && report.retries <= report.chunks * (MAX_ATTEMPTS - 1)
            && !report.atomic
            && report.sha256 == entry.sha256,
        "invalid external snapshot consistency evidence"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Memory {
        calls: usize,
        fail: bool,
        short: bool,
    }
    impl ReadMemory for Memory {
        async fn read(&mut self, address: u32, size: usize) -> Result<Vec<u8>> {
            self.calls += 1;
            let mut data = vec![(address / 4096) as u8; size];
            // A changing record is retried; a persistently changing block fails.
            if (self.fail && self.calls % 2 == 0) || (!self.fail && self.calls == 2) {
                data[0] ^= 1;
            }
            if self.short {
                data.pop();
            }
            Ok(data)
        }
    }
    #[tokio::test]
    async fn chunk_pairs_retry_and_record_non_atomic_scope() {
        let dir = tempfile::tempdir().unwrap();
        let entry = acquire_external(
            &mut Memory {
                calls: 0,
                fail: false,
                short: false,
            },
            dir.path(),
            PREFIX,
            0x98000000,
            0x300000,
        )
        .await
        .unwrap();
        verify_external_consistency(dir.path(), &entry).unwrap();
        let path = dir.path().join(format!("{PREFIX}.consistency.json"));
        let mut report: ExternalConsistency =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(report.retries, 1);
        assert!(!report.atomic);
        report.atomic = true;
        fs::write(path, serde_json::to_vec(&report).unwrap()).unwrap();
        assert!(verify_external_consistency(dir.path(), &entry).is_err());
    }
    #[tokio::test]
    async fn continuously_changing_or_short_block_never_creates_success_evidence() {
        let dir = tempfile::tempdir().unwrap();
        assert!(
            acquire_external(
                &mut Memory {
                    calls: 0,
                    fail: true,
                    short: false,
                },
                dir.path(),
                PREFIX,
                0x98000000,
                0x300000
            )
            .await
            .is_err()
        );
        assert!(!dir.path().join(PREFIX).exists());
        assert!(!dir.path().join(format!("{PREFIX}.verified.json")).exists());
        assert!(
            acquire_external(
                &mut Memory {
                    calls: 0,
                    fail: false,
                    short: true
                },
                dir.path(),
                PREFIX,
                0x98000000,
                0x300000
            )
            .await
            .is_err()
        );
        assert!(!dir.path().join(PREFIX).exists());
    }
}
