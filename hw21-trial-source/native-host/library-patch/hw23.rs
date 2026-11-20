// SPDX-License-Identifier: MIT
//! Exact-build overlay profile. The HW2.1 trial selects a different loader and commit layout.
//! Standard FirmwareImage::parse and its bounds remain unchanged.
use super::*;
use aes::{
    Aes128,
    cipher::{BlockCipherEncrypt, KeyInit},
};
use sha2::{Digest, Sha256};

pub const MAX_BYTES: usize = 0x74000; // End 0x78000: two extra 8 KiB sectors.
const STOCK_LEN: usize = 0x6f8c0;
const TAIL_OFFSET: usize = 0x70000;
const ENTRY: usize = 0x1ebb0 - 0x4000;
const LOOP: usize = 0x1ec04 - 0x4000;
const ENTRY_BEFORE: [u8; 8] = [0x40, 0xf2, 0x24, 0x24, 0xc4, 0xf2, 0xa7, 0x24];
const ENTRY_AFTER: [u8; 8] = [0x54, 0xf0, 0x86, 0xbe, 0x00, 0xbf, 0x00, 0xbf];
const LOOP_BEFORE: [u8; 4] = [0x1a, 0xf0, 0x08, 0xff];
const LOOP_AFTER: [u8; 4] = [0xc0, 0x47, 0x00, 0xbf];
const PREFIX_HASH: &str = "1440925005e848ff4d7b17fabb4a015a972b2b4dd519ed7c7a7352f8b236d1bf";
pub const TARGET_HW: &str = if cfg!(feature = "hw21-trial") {
    "2.1"
} else {
    "2.3"
};
pub const LOADER_HASH: &str = if cfg!(feature = "hw21-trial") {
    "17d51eeff9fb6abe1a7024a108006248e0aaebdaae52de69a3e26c000565d4bf"
} else {
    "8e972bbd2abffa199d465082f473823372e32d4b4c86574664a976afd2797809"
};
#[cfg(feature = "hw21-trial")]
const TRIAL_GATE_LEN: usize = 268;
#[cfg(feature = "hw21-trial")]
const TRIAL_EXTENSION_LEN: usize = 15_784;
#[cfg(feature = "hw21-trial")]
const TRIAL_GATE_HASH: &str = "0d8089b74a0dca4fed1e16e19bb356745943ab9efced926a2c4c1dc109a127ee";
#[cfg(feature = "hw21-trial")]
const TRIAL_EXTENSION_HASH: &str =
    "71ac5258858e726055fee19c91a8e56b01fbc9f745ec74478bce0abc9ff0f78d";
#[cfg(feature = "hw21-trial")]
const BOOT_V3_EXTENSION_LEN: usize = 15_668;
#[cfg(feature = "hw21-trial")]
const BOOT_V3_EXTENSION_HASH: &str =
    "f751af3d67aa153da11cc70aef342e05d5e76306b71a234fc16c764395a941b8";
#[cfg(feature = "hw21-trial")]
const BOOT_V2_EXTENSION_LEN: usize = 15_532;
#[cfg(feature = "hw21-trial")]
const BOOT_V2_EXTENSION_HASH: &str =
    "d62afa50533f5d208537d1866fc04c77202add03b47a092b0804b8ae435edadb";
#[cfg(feature = "hw21-trial")]
const PREVIOUS_EXTENSION_LEN: usize = 15_516;
#[cfg(feature = "hw21-trial")]
const PREVIOUS_EXTENSION_HASH: &str =
    "d2687c4fc7b27d55ab934d2dda74d9b6a7830254d786f78cd7f3bdc3b4c4778b";
const STOCK_HASH_PREFIX: [u8; 16] = [
    0xc6, 0x30, 0x57, 0xea, 0xf0, 0x8b, 0x86, 0x25, 0xe7, 0xac, 0x2f, 0xc7, 0x27, 0x0c, 0x06, 0xd7,
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Overlay,
    RollbackErasePass,
}

fn digest(data: &[u8]) -> String {
    hex::encode(Sha256::digest(data))
}

pub fn verify_loader(loader: &[u8]) -> Result<(), KMError> {
    if loader.len() != 0x3ffc || digest(loader) != LOADER_HASH {
        return Err(invalid(format!(
            "HW{TARGET_HW} extension requires the exact qualified loader"
        )));
    }
    Ok(())
}

pub fn validate_payload(data: &[u8]) -> Result<Kind, KMError> {
    let kind = validate_with_prefix(data, PREFIX_HASH)?;
    #[cfg(feature = "hw21-trial")]
    {
        let extension_hash = match data.len().checked_sub(TAIL_OFFSET) {
            Some(TRIAL_EXTENSION_LEN) => TRIAL_EXTENSION_HASH,
            Some(BOOT_V3_EXTENSION_LEN) => BOOT_V3_EXTENSION_HASH,
            Some(BOOT_V2_EXTENSION_LEN) => BOOT_V2_EXTENSION_HASH,
            Some(PREVIOUS_EXTENSION_LEN) => PREVIOUS_EXTENSION_HASH,
            _ => return Err(invalid("HW2.1 trial requires an exact supported transfer length")),
        };
        let gate_end = STOCK_LEN + TRIAL_GATE_LEN;
        if kind == Kind::Overlay
            && (digest(&data[STOCK_LEN..gate_end]) != TRIAL_GATE_HASH
                || data[gate_end..TAIL_OFFSET].iter().any(|&byte| byte != 0xff)
                || digest(&data[TAIL_OFFSET..]) != extension_hash)
        {
            return Err(invalid("HW2.1 trial gate, padding or extension differs"));
        }
    }
    Ok(kind)
}

#[cfg(feature = "hw21-trial")]
pub(super) fn trial_commit(data: &[u8]) -> Result<(u32, u32), KMError> {
    let length = match validate_payload(data)? {
        Kind::Overlay => STOCK_LEN + TRIAL_GATE_LEN,
        Kind::RollbackErasePass => STOCK_LEN,
    };
    Ok((length as u32, crc32fast::hash(&data[..length])))
}

pub(super) fn validate_ciphertext(image: &FirmwareImage) -> Result<(), KMError> {
    // The native writer sends every ciphertext byte, not only metadata.size.
    // An extra AES block must never spill into the next protected sector.
    if image.encrypted_data.len() != image.data.len().div_ceil(16) * 16 {
        return Err(invalid(
            "Extended image ciphertext must use minimal AES alignment",
        ));
    }
    let plain = aes_ecb_decrypt_blocks(&image.encrypted_data, &MEMORY_READ_KEY)?;
    if plain[image.data.len()..].iter().any(|byte| *byte != 255) {
        return Err(invalid(
            "Extended image AES alignment padding must be erased bytes",
        ));
    }
    Ok(())
}

fn validate_with_prefix(data: &[u8], prefix_hash: &str) -> Result<Kind, KMError> {
    if !(TAIL_OFFSET + 68..=MAX_BYTES).contains(&data.len()) || !data.len().is_multiple_of(4) {
        return Err(invalid("Extension size exceeds its two-sector profile"));
    }
    if data[IMAGE_METADATA_OFFSET..IMAGE_METADATA_OFFSET + 8] != [0xff; 8] {
        return Err(invalid("Extension image must have uncommitted size/CRC"));
    }
    let is_erase = data[ENTRY..ENTRY + 8] == ENTRY_BEFORE && data[LOOP..LOOP + 4] == LOOP_BEFORE;
    let kind = if is_erase {
        if data[STOCK_LEN..].iter().any(|b| *b != 255) {
            return Err(invalid(
                "Rollback erase pass must contain only erased bytes after stock",
            ));
        }
        Kind::RollbackErasePass
    } else {
        if data[ENTRY..ENTRY + 8] != ENTRY_AFTER || data[LOOP..LOOP + 4] != LOOP_AFTER {
            return Err(invalid("GUI hook differs from the exact-build profile"));
        }
        let tail = &data[TAIL_OFFSET..];
        let word = |at| u32::from_le_bytes(tail[at..at + 4].try_into().unwrap());
        if tail[..8] != *b"KPDX207\0"
            || word(8) != 1
            || word(12) as usize != tail.len()
            || tail[44..60] != STOCK_HASH_PREFIX
            || word(60) != 0
        {
            return Err(invalid("Invalid exact-build extension header"));
        }
        let mut crc = crc32fast::Hasher::new();
        crc.update(&tail[..16]);
        crc.update(&[0; 4]);
        crc.update(&tail[20..]);
        if crc.finalize() != word(16) {
            return Err(invalid("Extension CRC mismatch"));
        }
        for at in (20..44).step_by(4) {
            let pointer = word(at);
            if pointer & 1 == 0 || !(0x74040..0x74000 + tail.len() as u32).contains(&(pointer & !1))
            {
                return Err(invalid("Extension API pointer outside validated code"));
            }
        }
        Kind::Overlay
    };
    let mut prefix = data[..STOCK_LEN].to_vec();
    prefix[ENTRY..ENTRY + 8].copy_from_slice(&ENTRY_BEFORE);
    prefix[LOOP..LOOP + 4].copy_from_slice(&LOOP_BEFORE);
    if digest(&prefix) != prefix_hash {
        return Err(invalid(
            "Image modifies stock outside the two permitted GUI patches",
        ));
    }
    Ok(kind)
}

/// Parse only after an offline qualified-loader check. Live update rechecks it.
pub fn parse(bytes: &[u8], qualified_loader: &[u8]) -> Result<FirmwareImage, KMError> {
    verify_loader(qualified_loader)?;
    let image = FirmwareImage::parse_profile(bytes, ImageProfile::Hw23Overlay)?;
    image.validate_for_update()?;
    Ok(image)
}

/// Build a normal Qt/AES container using the library's existing key and AES crate.
/// No key derivation or alternate authentication/update protocol is introduced.
pub fn package(raw: &[u8], qualified_loader: &[u8]) -> Result<Vec<u8>, KMError> {
    verify_loader(qualified_loader)?;
    validate_payload(raw)?;
    let encoded = encode(raw, &format!("Exact HW{TARGET_HW} experimental overlay"))?;
    parse(&encoded, qualified_loader)?;
    Ok(encoded)
}

#[cfg(feature = "hw21-trial")]
pub fn trial_candidate(
    original: &[u8],
    gate: &[u8],
    extension: &[u8],
) -> Result<(Vec<u8>, Vec<u8>), KMError> {
    if original.len() != STOCK_LEN
        || gate.len() != TRIAL_GATE_LEN
        || !matches!(
            extension.len(),
            TRIAL_EXTENSION_LEN | BOOT_V3_EXTENSION_LEN | BOOT_V2_EXTENSION_LEN | PREVIOUS_EXTENSION_LEN
        )
    {
        return Err(invalid("Unexpected stock or trial overlay size"));
    }
    let mut restore = original.to_vec();
    restore[IMAGE_METADATA_OFFSET..IMAGE_METADATA_OFFSET + 8].fill(255);
    restore.resize(TAIL_OFFSET + extension.len(), 255);
    let mut overlay = restore.clone();
    overlay[ENTRY..ENTRY + 8].copy_from_slice(&ENTRY_AFTER);
    overlay[LOOP..LOOP + 4].copy_from_slice(&LOOP_AFTER);
    overlay[STOCK_LEN..STOCK_LEN + TRIAL_GATE_LEN].copy_from_slice(gate);
    overlay[TAIL_OFFSET..].copy_from_slice(extension);
    validate_payload(&overlay)?;
    validate_payload(&restore)?;
    Ok((overlay, restore))
}

#[cfg(feature = "hw21-trial")]
pub fn stock_restore(original: &[u8]) -> Result<Vec<u8>, KMError> {
    if original.len() != STOCK_LEN {
        return Err(invalid("Unexpected stock application size"));
    }
    let mut raw = original.to_vec();
    raw[IMAGE_METADATA_OFFSET..IMAGE_METADATA_OFFSET + 8].fill(255);
    let encoded = encode(&raw, "Original stock application")?;
    if FirmwareImage::parse(&encoded)?.installed_data()? != original {
        return Err(invalid(
            "Stock package does not reproduce original application",
        ));
    }
    Ok(encoded)
}

fn encode(raw: &[u8], description: &str) -> Result<Vec<u8>, KMError> {
    let text = |offset| -> Result<String, KMError> {
        let value = &raw[offset..offset + 12];
        let end = value.iter().position(|b| *b == 0).unwrap_or(12);
        if end == 0 || end >= 12 || !value[..end].is_ascii() {
            return Err(invalid("Invalid embedded firmware identity"));
        }
        Ok(String::from_utf8(value[..end].to_vec()).unwrap())
    };
    let fields = vec![
        "Firmware file".to_owned(),
        "ChargerLab".into(),
        "V1.0".into(),
        text(0x430)?,
        text(0x43c)?,
        text(0x448)?,
        format!("{:08X}", crc32fast::hash(raw)),
        raw.len().to_string(),
        String::new(),
        description.into(),
    ];
    let mut encoded = (FIELD_COUNT as u32).to_be_bytes().to_vec();
    for field in fields {
        let bytes: Vec<_> = field.encode_utf16().flat_map(u16::to_be_bytes).collect();
        encoded.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
        encoded.extend(bytes);
    }
    let mut encrypted = raw.to_vec();
    encrypted.resize(raw.len().div_ceil(16) * 16, 255);
    let cipher = Aes128::new((&*MEMORY_READ_KEY).into());
    for block in encrypted.as_chunks_mut::<16>().0 {
        cipher.encrypt_block(block.into());
    }
    encoded.extend_from_slice(&(encrypted.len() as u32).to_be_bytes());
    encoded.extend(encrypted);
    Ok(encoded)
}

/// Read-only preflight inside the library, before transfer_image can send Setup.
pub(super) async fn verify_live_loader(
    device: &mut KM003C,
    identity: &crate::auth::DeviceInfo,
) -> Result<(), KMError> {
    verify_transport_loader(device, identity).await
}

async fn verify_transport_loader(
    transport: &mut impl FirmwareTransport,
    identity: &crate::auth::DeviceInfo,
) -> Result<(), KMError> {
    if identity.model != "KM003C" || identity.hw_version != TARGET_HW {
        return Err(invalid(format!(
            "Extended update requires live KM003C HW{TARGET_HW} in native DFU"
        )));
    }
    verify_loader(&read_loader(transport).await?)
}

async fn read_loader(transport: &mut impl FirmwareTransport) -> Result<Vec<u8>, KMError> {
    let mut data = Vec::with_capacity(0x3ffc);
    while data.len() < 0x3ffc {
        let count = (0x3ffc - data.len()).min(4096);
        let at = 4 + data.len() as u32;
        let packet = crate::auth::build_memory_read_packet(at, count as u32, transport.next_id());
        transport.write(&packet).await?;
        let confirmation = transport.read(Duration::from_secs(5)).await?;
        expect_type(
            &confirmation,
            PacketType::MemoryRead,
            "Qualified loader preflight",
        )?;
        if confirmation.len() != 20
            || crate::auth::parse_memory_read_confirmation(&confirmation[4..])
                != Some((at, count as u32))
        {
            return Err(invalid("Invalid loader preflight confirmation"));
        }
        let aligned = count.div_ceil(16) * 16;
        let mut ciphertext = Vec::with_capacity(aligned);
        while ciphertext.len() < aligned {
            let chunk = transport.read(Duration::from_secs(5)).await?;
            if chunk.is_empty() || chunk.len() > aligned - ciphertext.len() {
                return Err(invalid("Invalid loader preflight length"));
            }
            ciphertext.extend(chunk);
        }
        let plain = crate::auth::decrypt_memory_read_response(&ciphertext)
            .ok_or_else(|| invalid("Invalid loader ciphertext"))?;
        data.extend_from_slice(&plain[..count]);
    }
    Ok(data)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn synthetic(overlay: bool) -> (Vec<u8>, String) {
        let mut data = vec![255; TAIL_OFFSET + 80];
        data[ENTRY..ENTRY + 8].copy_from_slice(&ENTRY_BEFORE);
        data[LOOP..LOOP + 4].copy_from_slice(&LOOP_BEFORE);
        let hash = digest(&data[..STOCK_LEN]);
        if overlay {
            data[ENTRY..ENTRY + 8].copy_from_slice(&ENTRY_AFTER);
            data[LOOP..LOOP + 4].copy_from_slice(&LOOP_AFTER);
            let tail = &mut data[TAIL_OFFSET..];
            tail[..8].copy_from_slice(b"KPDX207\0");
            for (offset, value) in [(8, 1u32), (12, 80), (16, 0), (60, 0)] {
                tail[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
            }
            for offset in (20..44).step_by(4) {
                tail[offset..offset + 4].copy_from_slice(&0x74041u32.to_le_bytes());
            }
            tail[44..60].copy_from_slice(&STOCK_HASH_PREFIX);
            let crc = crc32fast::hash(tail);
            tail[16..20].copy_from_slice(&crc.to_le_bytes());
        }
        (data, hash)
    }

    #[test]
    fn exact_patch_shape_and_rollback_are_bounded() {
        for overlay in [false, true] {
            let (mut data, hash) = synthetic(overlay);
            assert_eq!(
                validate_with_prefix(&data, &hash).unwrap(),
                if overlay {
                    Kind::Overlay
                } else {
                    Kind::RollbackErasePass
                }
            );
            assert!(validate_payload(&data).is_err()); // Synthetic bytes cannot pass the production hash.
            data[0x1000] ^= 1;
            assert!(validate_with_prefix(&data, &hash).is_err());
        }
        let (mut data, hash) = synthetic(true);
        data[TAIL_OFFSET + 79] ^= 1;
        assert!(validate_with_prefix(&data, &hash).is_err());
        data.resize(MAX_BYTES + 4, 255);
        assert!(validate_with_prefix(&data, &hash).is_err());
        assert!(verify_loader(&[255; 0x3ffc]).is_err());
    }

    #[test]
    fn ordinary_parser_retains_original_limit() {
        let oversized = super::super::tests::package(MAX_IMAGE_BYTES + 4, &[]);
        assert!(FirmwareImage::parse(&oversized).is_err());
    }

    #[test]
    fn ciphertext_cannot_add_a_block_or_non_erased_padding() {
        let mut image = super::super::tests::image(4156);
        validate_ciphertext(&image).unwrap();
        image.encrypted_data.extend_from_slice(&[0; 16]);
        assert!(validate_ciphertext(&image).is_err());
        let mut image = super::super::tests::image(4156);
        let mut plain = aes_ecb_decrypt_blocks(&image.encrypted_data, &MEMORY_READ_KEY).unwrap();
        *plain.last_mut().unwrap() = 0x12;
        let cipher = Aes128::new((&*MEMORY_READ_KEY).into());
        for block in plain.as_chunks_mut::<16>().0 {
            cipher.encrypt_block(block.into());
        }
        image.encrypted_data = plain;
        assert!(validate_ciphertext(&image).is_err());
    }

    struct ReadOnlyMock {
        replies: std::collections::VecDeque<Result<Vec<u8>, KMError>>,
        writes: Vec<Vec<u8>>,
    }
    impl FirmwareTransport for ReadOnlyMock {
        fn next_id(&mut self) -> u8 {
            self.writes.len() as u8
        }
        async fn write(&mut self, bytes: &[u8]) -> Result<(), KMError> {
            assert_eq!(
                PacketPeek::from_bytes(bytes).unwrap().packet_type,
                PacketType::MemoryRead,
                "Loader qualification must never send Setup or ciphertext"
            );
            self.writes.push(bytes.to_vec());
            Ok(())
        }
        async fn read(&mut self, _: Duration) -> Result<Vec<u8>, KMError> {
            self.replies
                .pop_front()
                .expect("Unexpected retry/extra read")
        }
    }
    fn read_mock() -> ReadOnlyMock {
        let mut replies = std::collections::VecDeque::new();
        let cipher = Aes128::new((&*MEMORY_READ_KEY).into());
        for (at, count) in [(4u32, 4096u32), (4100, 4096), (8196, 4096), (12292, 4092)] {
            let mut confirmation = vec![0xc4, 1, 1, 1];
            confirmation.extend_from_slice(&at.to_le_bytes());
            confirmation.extend_from_slice(&count.to_le_bytes());
            confirmation.extend_from_slice(&u32::MAX.to_le_bytes());
            let crc = crc32fast::hash(&confirmation[4..]);
            confirmation.extend_from_slice(&crc.to_le_bytes());
            let mut encrypted = vec![255; count.div_ceil(16) as usize * 16];
            for block in encrypted.as_chunks_mut::<16>().0 {
                cipher.encrypt_block(block.into());
            }
            replies.push_back(Ok(confirmation));
            replies.push_back(Ok(encrypted));
        }
        ReadOnlyMock {
            replies,
            writes: Vec::new(),
        }
    }
    fn identity(hw: &str) -> crate::auth::DeviceInfo {
        let mut info = crate::auth::DeviceInfo::default();
        info.model = "KM003C".into();
        info.hw_version = hw.into();
        info
    }

    #[tokio::test]
    async fn wrong_live_hardware_and_loader_stop_before_erase() {
        let other = if TARGET_HW == "2.1" { "2.3" } else { "2.1" };
        let mut usb = read_mock();
        assert!(
            verify_transport_loader(&mut usb, &identity(other))
                .await
                .is_err()
        );
        assert!(usb.writes.is_empty());
        let mut usb = read_mock();
        assert!(
            verify_transport_loader(&mut usb, &identity(TARGET_HW))
                .await
                .is_err()
        );
        assert_eq!(usb.writes.len(), 4);
        assert!(usb.replies.is_empty());
        assert_eq!(
            crate::auth::parse_memory_read_payload(&usb.writes[3][4..]),
            Some((12292, 4092))
        );
    }

    #[tokio::test]
    async fn malformed_or_disconnected_loader_read_is_never_retried() {
        for response in [
            Ok(vec![1]),
            Ok(vec![11, 0, 0, 0]),
            Err(KMError::Io(std::io::ErrorKind::BrokenPipe.into())),
        ] {
            let mut usb = read_mock();
            usb.replies[0] = response;
            assert!(
                verify_transport_loader(&mut usb, &identity(TARGET_HW))
                    .await
                    .is_err()
            );
            assert_eq!(usb.writes.len(), 1);
        }
        for payload in [vec![], vec![0; 4097]] {
            let mut usb = read_mock();
            usb.replies[1] = Ok(payload);
            assert!(
                verify_transport_loader(&mut usb, &identity(TARGET_HW))
                    .await
                    .is_err()
            );
            assert_eq!(usb.writes.len(), 1);
        }
    }
}
