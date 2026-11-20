"""Package the private dual-HW capture installer from the pinned stock-free ZIPs."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
NAME = "km003c-capture-HW2.1-HW2.3-fw2.0.7-UNIFIED-TRIAL-v1-windows-x64.zip"
SOURCE_KITS = {
    "hw21": (
        "c333d9a205f9d39e09cb96d7d5be573b9e4b2915f1ae6a3116a2777b9c30fa7c",
        ("overlay", "overlay-previous", "overlay-boot-v2", "overlay-boot-v3"),
    ),
    "hw23": (
        "8dea4698a2b9f3c855897ed209ed9277de900ba7fd20e5ee3818b1097784e6e3",
        ("overlays/screen",),
    ),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def kit_files(path: Path, key: str) -> dict[str, bytes]:
    expected, overlays = SOURCE_KITS[key]
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError(f"{key}: expected the original pinned source ZIP")
    with ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.namelist()
        if len(entries) != len(set(entries)):
            raise ValueError(f"{key}: duplicate archive member")
        keep = {"km003c-backup.exe", "km003c-overlay-host.exe", "LICENSE", "THIRD_PARTY_NOTICES.md"}
        keep.update(f"{overlay}/{file}" for overlay in overlays for file in ("gate.bin", "extension.bin", "build.json"))
        licenses = {name for name in entries if name.startswith("licenses/") and not name.endswith("/")}
        if not licenses or not keep.issubset(entries):
            raise ValueError(f"{key}: missing executable, overlay or license")
        keep.update(licenses)
        if any(not re.fullmatch(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", name)
               or {".", ".."}.intersection(name.split("/")) for name in keep):
            raise ValueError(f"{key}: unsafe member path")
        return {f"{key}/{name}": archive.read(name) for name in keep}


def package(hw21: Path, hw23: Path, output: Path) -> Path:
    ps_source = (ROOT / "windows/Install-Capture.ps1").read_text(encoding="utf-8-sig")
    launcher = (ROOT / "windows/Install-Capture.cmd").read_text(encoding="ascii")
    contents = {
        "Install.cmd": launcher.replace("\n", "\r\n").encode("ascii"),
        "Install-Capture.ps1": ps_source.encode("utf-8-sig"),
        "START-HERE.ja.md": (ROOT / "docs/INSTALL-CAPTURE-TRIAL.ja.md").read_bytes(),
        "LICENSE": (ROOT / "LICENSE").read_bytes(),
    }
    contents.update(kit_files(hw21, "hw21"))
    contents.update(kit_files(hw23, "hw23"))
    manifest = {
        "schema": 1,
        "firmware": "2.0.7",
        "distribution": "private trial",
        "stock_free": True,
        "source_kits": {key: digest_value for key, (digest_value, _) in SOURCE_KITS.items()},
        "files": [
            {"path": name, "bytes": len(data), "sha256": digest(data)}
            for name, data in sorted(contents.items())
        ],
    }
    contents["capture-trial-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output.mkdir(parents=True, exist_ok=True)
    path = output / NAME
    with ZipFile(path, "x", ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(contents.items()):
            archive.writestr(name, data)
    path.with_suffix(".zip.sha256").write_text(f"{digest(path.read_bytes())}  {path.name}\n", encoding="ascii")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hw21", type=Path, required=True)
    parser.add_argument("--hw23", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package(args.hw21, args.hw23, args.output))
