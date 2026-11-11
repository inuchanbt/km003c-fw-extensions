// SPDX-License-Identifier: MIT. Bounded read-only qualification in native DFU.
#[allow(dead_code)]
#[path = "../src/bundle.rs"]
mod bundle;
use anyhow::{Result, ensure};
use clap::Parser;
use km003c_backup::{ReadMemory, Reader, digest, save, save_json};
use km003c_lib::{
    DeviceSelector, KM003C,
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
    let a = Args::parse();
    let s = bundle::stock(&a.stock)?;
    let b = bundle::audit(&s, &a.stock, &a.bundle)?;
    ensure!(!a.output.exists(), "Output must be new");
    let port = DeviceSelector::PortPath {
        bus_id: s.manifest.usb_port.bus_id.clone(),
        port_chain: s.manifest.usb_port.port_chain.clone(),
    };
    ensure!(
        find_firmware_device(&port).await?.mode == FirmwareUsbMode::Dfu,
        "Native DFU required"
    );
    let mut device = KM003C::open_maintenance(port).await?;
    let info = device.get_bootloader_info().await?;
    ensure!(
        info.model == "KM003C" && info.hw_version == "2.3",
        "Wrong device"
    );
    let mut r = Reader { device, dfu: true };
    let loader = r.read(4, 0x3ffc).await?;
    ensure!(loader == s.loader, "Loader differs");
    let internal = r.read(0x4000, 0x7c000).await?;
    ensure!(internal == b.overlay_state, "Internal firmware differs");
    fs::create_dir(&a.output)?;
    save(&a.output.join("loader.bin"), &loader)?;
    save(&a.output.join("internal.bin"), &internal)?;
    for (name, address, size) in [
        ("candidate", 0x98380000, 0x70000),
        ("settings-guard", 0x983f0000, 0x10000),
    ] {
        let first = r.read(address, size).await?;
        let second = r.read(address, size).await?;
        save(&a.output.join(format!("{name}-first.bin")), &first)?;
        save(&a.output.join(format!("{name}-second.bin")), &second)?;
        ensure!(first == second, "NOR changed between reads");
        save_json(
            &a.output.join(format!("{name}.json")),
            &json!({"address":address,"bytes":size,"matching_reads":true,"all_ff":first.iter().all(|b| *b==255),"sha256":digest(&first),"read_only":true}),
        )?;
    }
    println!(
        "Read-only tail qualification complete; loader/internal matched. Device remains in DFU."
    );
    Ok(())
}
