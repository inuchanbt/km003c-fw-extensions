// SPDX-License-Identifier: MIT
//! Read-only GUI evidence while capture storage differs from the blank backup.
//! Does not call update, erase, start, DFU or settings APIs.
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
    /// Read external NOR twice as well; never sends program, erase or format.
    #[arg(long)]
    external: bool,
    /// Mapped NOR bytes to inspect (some native APP builds restrict the tail).
    #[arg(long, default_value_t = 0x100000)]
    external_bytes: usize,
    /// Offset within the 4 MiB NOR; APP may restrict reads above 4,000,000.
    #[arg(long, default_value_t = 0)]
    external_offset: u32,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let stock = bundle::stock(&args.stock)?;
    let image = bundle::audit(&stock, &args.stock, &args.bundle)?;
    fs::create_dir(&args.output)?;
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
            && info.fw_version == "2.0.7"
            && info.serial_id == stock.manifest.identity.serial,
        "Qualified device identity differs"
    );
    let mut reader = Reader { device, dfu: false };
    let loader = reader.read(4, 0x3ffc).await?;
    save(&args.output.join("loader.bin"), &loader)?;
    ensure!(loader == stock.loader, "Loader differs");
    let internal = reader.read(0x4000, 0x7c000).await?;
    save(&args.output.join("internal.bin"), &internal)?;
    let capture = 0x78000 - bundle::BASE;
    let end = 0x7c000 - bundle::BASE;
    ensure!(
        internal[..capture] == image.overlay_state[..capture]
            && internal[end..] == stock.baseline[end..],
        "Bytes outside capture storage differ"
    );
    let calibration = reader.read(0x03000c00, 1024).await?;
    save(&args.output.join("calibration.bin"), &calibration)?;
    ensure!(calibration == stock.calibration, "Calibration differs");
    let ram = reader.read(0x1fff8000, 0x2f000).await?;
    save(&args.output.join("sram.bin"), &ram)?;
    let at = 0x2001a8d0 - 0x1fff8000;
    let pool = u32::from_le_bytes(ram[at..at + 4].try_into()?);
    ensure!(pool == 0x200091e0, "Unrecognized native heap");
    let heap = reader.read(pool, 0x8000).await?;
    save(&args.output.join("lvgl-heap.bin"), &heap)?;
    if args.external {
        ensure!(
            args.external_bytes >= 0x1000
                && args.external_bytes <= 0x400000
                && u64::from(args.external_offset) + args.external_bytes as u64 <= 0x400000,
            "External read must stay inside the 4 MiB NOR"
        );
        let address = 0x98000000 + args.external_offset;
        let first = reader.read(address, args.external_bytes).await?;
        save(&args.output.join("external-first.bin"), &first)?;
        let second = reader.read(address, args.external_bytes).await?;
        save(&args.output.join("external-second.bin"), &second)?;
        save_json(
            &args.output.join("external-snapshot.json"),
            &json!({
                "schema":1,"read_only":true,"private_data_must_not_be_published":true,
                "address":address,"bytes":first.len(),"matching_full_reads":first==second,
                "first_sha256":digest(&first),"second_sha256":digest(&second),
                "first_mib_matches":if args.external_offset==0 && first.len()>=0x100000 {
                    Some(first[..0x100000]==second[..0x100000])
                } else { None },
                "factory_sector_matches":if args.external_offset==0 && first.len()==0x400000 {
                    Some(first[0x3ff000..]==second[0x3ff000..])
                } else { None },
                "firmware_writes":0,"atomic_snapshot":false
            }),
        )?;
    }
    save_json(
        &args.output.join("gui-snapshot.json"),
        &json!({
            "schema":1,"read_only":true,"private_ram_must_not_be_published":true,
            "state":"known-overlay-with-capture-data","sram_base":0x1fff8000u32,
            "sram_bytes":ram.len(),"lvgl_heap_base":pool,"lvgl_heap_bytes":heap.len(),
            "protected_internal_bytes_match":true,"loader_matches":true,"calibration_matches":true,
            "capture_bytes_unmodified":true,"firmware_writes":0,"atomic_snapshot":false
        }),
    )?;
    println!(
        "Read-only capture/GUI evidence saved; code, loader and calibration matched. No device changes sent."
    );
    Ok(())
}
