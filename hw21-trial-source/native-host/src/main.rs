// SPDX-License-Identifier: MIT
mod bundle;
mod device;
use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::PathBuf;

#[derive(Parser)]
#[command(about = "Exact stock-2.0.7 overlay packaging and qualified native-loader access")]
#[cfg_attr(feature = "hw21-trial", command(version = concat!(env!("CARGO_PKG_VERSION"), "-hw21-trial")))]
struct Args {
    #[arg(long)]
    stock: PathBuf,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    /// In DFU: rewrite verified stock and clear only an exactly identified legacy QR residue.
    #[cfg(feature = "hw21-trial")]
    CleanupKnownQr {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Read-only private SRAM snapshot for exact-build GUI analysis.
    InspectGui {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Verify a known healthy application before requesting native DFU. No flash write.
    EnterDfu {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Offline only: create extended overlay, erase pass and original restore bundle.
    Package {
        #[arg(long)]
        candidate: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Offline only: prepare the HW2.1 trial and rollback from a verified backup.
    #[cfg(feature = "hw21-trial")]
    PackageTrial {
        #[arg(long)]
        overlay: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Offline only: verify package bytes, profile and complete modeled rollback.
    Audit {
        #[arg(long)]
        bundle: PathBuf,
    },
    /// Read only; accepts stock APP or manually entered native DFU.
    CheckDevice {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// In manually entered native DFU: install the call-through probe; never starts it.
    FlashProbe {
        #[arg(long)]
        bundle: PathBuf,
        /// Audited previous probe whose complete installed bytes may be replaced.
        #[arg(long)]
        previous_bundle: Option<PathBuf>,
        #[arg(long)]
        output: PathBuf,
    },
    /// In native DFU: erase added sectors, then restore exact original application.
    Restore {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Verify all installed bytes in native DFU before starting the probe.
    StartProbe {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Verify exact original bytes in native DFU before starting stock.
    StartStock {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
}
#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    if let Command::Package { candidate, output } = args.command {
        return bundle::package(&args.stock, &candidate, &output);
    }
    #[cfg(feature = "hw21-trial")]
    if let Command::PackageTrial { overlay, output } = args.command {
        return bundle::package_trial(&args.stock, &overlay, &output);
    }
    let s = bundle::stock(&args.stock)?;
    match args.command {
        #[cfg(feature = "hw21-trial")]
        Command::CleanupKnownQr { bundle: path, output } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            device::cleanup_known_qr(&s, &b, &output).await?;
        }
        Command::InspectGui {
            bundle: path,
            output,
        } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            device::inspect_gui(&s, &b, &output).await?;
        }
        Command::EnterDfu {
            bundle: path,
            output,
        } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            device::enter_dfu(&s, &b, &output).await?;
        }
        Command::Audit { bundle: path } => {
            let _ = bundle::audit(&s, &args.stock, &path)?;
            println!("Offline bundle audit passed. No USB accessed.");
        }
        Command::CheckDevice {
            bundle: path,
            output,
        } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            device::check(&s, &b, &output).await?;
        }
        Command::FlashProbe {
            bundle: path,
            previous_bundle,
            output,
        } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            let previous = previous_bundle
                .as_ref()
                .map(|path| bundle::audit(&s, &args.stock, path))
                .transpose()?;
            device::flash(&s, &b, previous.as_ref(), &output).await?;
        }
        Command::Restore {
            bundle: path,
            output,
        } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            device::restore(&s, &b, &output).await?;
        }
        Command::StartProbe {
            bundle: path,
            output,
        } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            device::start(&s, &b, &output, true).await?;
        }
        Command::StartStock {
            bundle: path,
            output,
        } => {
            let b = bundle::audit(&s, &args.stock, &path)?;
            device::start(&s, &b, &output, false).await?;
        }
        Command::Package { .. } => unreachable!(),
        #[cfg(feature = "hw21-trial")]
        Command::PackageTrial { .. } => unreachable!(),
    }
    Ok(())
}
