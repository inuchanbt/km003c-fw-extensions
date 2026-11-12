// SPDX-License-Identifier: MIT
//! Stock-free distribution inputs; all firmware is derived privately at runtime.
use crate::bundle;
use anyhow::{Result, ensure};
use clap::ValueEnum;
use km003c_backup as backup;
use km003c_lib::firmware::hw23;
use serde_json::json;
use std::{fs, path::Path};

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum Variant {
    Qr,
    Screen,
}

fn components(folder: &Path, variant: Variant) -> Result<(Vec<u8>, Vec<u8>)> {
    let (gate_hash, extension_hash) = match variant {
        Variant::Qr => (
            "ffc18d85c1cbccad49dc597cb44894597176129cb0821f4bbd5d0183f521d556",
            "4140de1a80beef119b18de0f12bc0ebbcfe74c2c579bb24941694173ee4e25f0",
        ),
        Variant::Screen => (
            "0d8089b74a0dca4fed1e16e19bb356745943ab9efced926a2c4c1dc109a127ee",
            "d2687c4fc7b27d55ab934d2dda74d9b6a7830254d786f78cd7f3bdc3b4c4778b",
        ),
    };
    let gate = fs::read(folder.join("gate.bin"))?;
    let extension = fs::read(folder.join("extension.bin"))?;
    ensure!(
        backup::digest(&gate) == gate_hash && backup::digest(&extension) == extension_hash,
        "Components differ from the hardware-qualified variant; download the matching release"
    );
    Ok((gate, extension))
}

fn assemble(original: &[u8], gate: &[u8], extension: &[u8]) -> Result<(Vec<u8>, Vec<u8>)> {
    ensure!(
        original.len() == 0x738c0 - bundle::BASE
            && !gate.is_empty()
            && gate.len() <= 0x74000 - 0x738c0
            && gate.len().is_multiple_of(4)
            && (68..=0x4000).contains(&extension.len())
            && extension.len().is_multiple_of(4),
        "Component or application bounds are invalid"
    );
    let mut candidate = original.to_vec();
    candidate.resize(0x74000 - bundle::BASE + extension.len(), 255);
    candidate[0x428..0x430].fill(255);
    let erase = candidate.clone();
    candidate[0x1ebb0 - bundle::BASE..0x1ebb8 - bundle::BASE]
        .copy_from_slice(&[0x54, 0xf0, 0x86, 0xbe, 0x00, 0xbf, 0x00, 0xbf]);
    candidate[0x1ec04 - bundle::BASE..0x1ec08 - bundle::BASE]
        .copy_from_slice(&[0xc0, 0x47, 0x00, 0xbf]);
    candidate[0x738c0 - bundle::BASE..0x738c0 - bundle::BASE + gate.len()].copy_from_slice(gate);
    candidate[0x74000 - bundle::BASE..].copy_from_slice(extension);
    Ok((candidate, erase))
}

pub fn prepare(stock: &Path, overlay: &Path, variant: Variant, output: &Path) -> Result<()> {
    let (gate, extension) = components(overlay, variant)?;
    let s = bundle::stock(stock)?;
    let (candidate, erase) = assemble(&s.original, &gate, &extension)?;
    hw23::validate_payload(&candidate)?;
    hw23::validate_payload(&erase)?;
    ensure!(!output.exists(), "Private output must be a NEW directory");
    fs::create_dir(output)?;
    let raw = output.join("candidate");
    fs::create_dir(&raw)?;
    backup::save(&raw.join("candidate-uncommitted.bin"), &candidate)?;
    backup::save(&raw.join("rollback-erase-pass-uncommitted.bin"), &erase)?;
    bundle::package(stock, &raw, &output.join("bundle"))?;
    backup::save_json(
        &output.join("prepared.json"),
        &json!({
            "schema":1, "stock_firmware":"2.0.7", "hardware":"2.3",
            "variant":format!("{variant:?}").to_lowercase(), "usb_access":false,
            "owner_generated_private_firmware":true,
            "gate_sha256":backup::digest(&gate), "extension_sha256":backup::digest(&extension)
        }),
    )?;
    println!(
        "Ready: {}. Keep this PRIVATE with your stock backup.",
        output.join("bundle").display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn untrusted_or_swapped_components_stop_before_backup_or_usb_access() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("gate.bin"), [0; 264]).unwrap();
        fs::write(dir.path().join("extension.bin"), [0; 80]).unwrap();
        for variant in [Variant::Qr, Variant::Screen] {
            let out = dir.path().join("output");
            let err =
                prepare(&dir.path().join("missing-stock"), dir.path(), variant, &out).unwrap_err();
            assert!(err.to_string().contains("hardware-qualified"));
            assert!(!out.exists());
        }
    }
    #[test]
    fn assembly_preserves_stock_outside_hooks_and_recovery_erases_added_bytes() {
        let original = vec![0x12; 0x738c0 - bundle::BASE];
        let (candidate, erase) = assemble(&original, &[0x34; 264], &[0x56; 80]).unwrap();
        let mut prefix = candidate[..original.len()].to_vec();
        for span in [
            0x428..0x430,
            0x1ebb0 - bundle::BASE..0x1ebb8 - bundle::BASE,
            0x1ec04 - bundle::BASE..0x1ec08 - bundle::BASE,
        ] {
            prefix[span.clone()].copy_from_slice(&original[span]);
        }
        assert_eq!(prefix, original);
        assert!(erase[original.len()..].iter().all(|b| *b == 255));
        assert_eq!(&erase[0x428..0x430], &[255; 8]);
        assert!(assemble(&original, &[0; 0x800], &[0; 80]).is_err());
        assert!(assemble(&original, &[0; 264], &[0; 0x4004]).is_err());
    }
}
