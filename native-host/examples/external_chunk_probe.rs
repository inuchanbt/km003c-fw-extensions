// SPDX-License-Identifier: MIT
//! Read-only experiment: compare consecutive chunks of a live external NOR.
#[allow(dead_code)]
#[path = "../src/bundle.rs"]
mod bundle;
use anyhow::{Result, ensure};
use clap::Parser;
use km003c_backup::{ReadMemory, Reader, digest, save, save_json};
use km003c_lib::{
    DeviceConfig, DeviceSelector, KM003C,
    firmware::{FirmwareUsbMode, find_firmware_device},
};
use serde_json::json;
use std::{fs, path::PathBuf};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    stock: PathBuf,
    #[arg(long)]
    bundle: PathBuf,
    #[arg(long)]
    output: PathBuf,
}
#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let stock = bundle::stock(&args.stock)?;
    let image = bundle::audit(&stock, &args.stock, &args.bundle)?;
    ensure!(!args.output.exists(), "Output must be new");
    let port = DeviceSelector::PortPath {
        bus_id: stock.manifest.usb_port.bus_id.clone(),
        port_chain: stock.manifest.usb_port.port_chain.clone(),
    };
    let found = find_firmware_device(&port).await?;
    ensure!(
        found.mode == FirmwareUsbMode::Application
            && found.product_string.as_deref() == Some("POWER-Z KM003C"),
        "Known application required"
    );
    let mut device = KM003C::new(DeviceConfig::vendor().skip_reset().select(port)).await?;
    let info = device.get_device_info().await?;
    ensure!(
        info.model == "KM003C"
            && info.hw_version == "2.3"
            && info.serial_id == stock.manifest.identity.serial,
        "Device differs"
    );
    let mut reader = Reader { device, dfu: false };
    ensure!(
        reader.read(4, 0x3ffc).await? == stock.loader,
        "Loader differs"
    );
    ensure!(
        reader.read(0x4000, 0x7c000).await? == image.overlay_state,
        "Internal firmware differs"
    );
    ensure!(
        reader.read(0x03000c00, 1024).await? == stock.calibration,
        "Calibration differs"
    );
    fs::create_dir(&args.output)?;
    let mut snapshot = Vec::with_capacity(0x300000);
    let mut differences = Vec::new();
    for offset in (0..0x300000).step_by(4096) {
        let address = 0x98000000 + offset as u32;
        let first = reader.read(address, 4096).await?;
        let second = reader.read(address, 4096).await?;
        if first != second {
            differences.push(json!({"offset":offset,"different_bytes":first.iter().zip(&second).filter(|(a,b)| a!=b).count()}));
        }
        snapshot.extend_from_slice(&first);
    }
    save(&args.output.join("external-private.bin"), &snapshot)?;
    save_json(
        &args.output.join("result.json"),
        &json!({"schema":1,"bytes":snapshot.len(),"chunk_bytes":4096,
        "read_only":true,"atomic":false,"differing_chunks":differences,"snapshot_sha256":digest(&snapshot)}),
    )?;
    println!("Read-only consecutive-chunk comparison finished. Private evidence saved.");
    Ok(())
}
