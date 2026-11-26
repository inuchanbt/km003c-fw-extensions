"""Package the dual-HW capture installer from the pinned stock-free ZIPs."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
NAME = "km003c-capture-v0.3.2-HW2.1-HW2.3-fw2.0.7-windows-x64.zip"
OVERLAY_FILES = ("gate.bin", "extension.bin", "build.json")
THEMES = {
    "hw21": (
        "overlay",
        "0d8089b74a0dca4fed1e16e19bb356745943ab9efced926a2c4c1dc109a127ee",
        "568c4a92165a7df4eb4514465a4f92956f1ffd9edb6c4f53f9d493e2a80adb18",
    ),
    "hw23": (
        "overlays/screen-themes",
        "23fa02d947598e9eb4ff517df286ffb392e35825c17579f95faed2d6c72a5d48",
        "2fdda587bbb17e432d4a4b1e432bafcb408e27d4358f2bbba70c85033549d0c4",
    ),
}
SOURCE_KITS = {
    "hw21": (
        "31ddc18562105fba9fb67432721836fb65b674cdc1cb1577b66628af46502e38",
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
        prefix = "hw21/" if key == "hw21" else ""
        entries = {name.removeprefix(prefix) for name in entries if name.startswith(prefix)}
        keep = {"km003c-backup.exe", "km003c-overlay-host.exe", "LICENSE", "THIRD_PARTY_NOTICES.md"}
        keep.update(f"{overlay}/{file}" for overlay in overlays for file in OVERLAY_FILES)
        licenses = {name for name in entries if name.startswith("licenses/") and not name.endswith("/")}
        if not licenses or not keep.issubset(entries):
            raise ValueError(f"{key}: missing executable, overlay or license")
        keep.update(licenses)
        if any(not re.fullmatch(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", name)
               or {".", ".."}.intersection(name.split("/")) for name in keep):
            raise ValueError(f"{key}: unsafe member path")
        return {f"{key}/{name}": archive.read(prefix + name) for name in keep}


def themes_kit(key: str, source: Path, overlay: Path, host: Path) -> dict[str, bytes]:
    files = kit_files(source, key)
    if key == "hw21":
        for name in OVERLAY_FILES:
            files[f"hw21/overlay-boot-v4/{name}"] = files[f"hw21/overlay/{name}"]
    folder, gate_hash, extension_hash = THEMES[key]
    components = {name: (overlay / name).read_bytes() for name in OVERLAY_FILES}
    if (digest(components["gate.bin"]), digest(components["extension.bin"])) != (gate_hash, extension_hash):
        raise ValueError(f"{key}: Themes components differ from the exact verified build")
    files.update({f"{key}/{folder}/{name}": raw for name, raw in components.items()})
    files[f"{key}/km003c-overlay-host.exe"] = host.read_bytes()
    return files


def package(hw21: Path, hw23: Path, overlay21: Path, overlay23: Path,
            host21: Path, host23: Path, output: Path) -> Path:
    ps_source = (ROOT / "windows/Install-Capture.ps1").read_text(encoding="utf-8-sig")
    launcher = (ROOT / "windows/Install-Capture.cmd").read_text(encoding="ascii")
    contents = {
        "Install.cmd": launcher.replace("\n", "\r\n").encode("ascii"),
        "Install-Capture.ps1": ps_source.encode("utf-8-sig"),
        "START-HERE.md": (ROOT / "docs/INSTALL-CAPTURE.md").read_bytes(),
        "START-HERE.ja.md": (ROOT / "docs/INSTALL-CAPTURE-TRIAL.ja.md").read_bytes(),
        "LICENSE": (ROOT / "LICENSE").read_bytes(),
    }
    contents.update(themes_kit("hw21", hw21, overlay21, host21))
    contents.update(themes_kit("hw23", hw23, overlay23, host23))
    manifest = {
        "schema": 1,
        "firmware": "2.0.7",
        "distribution": "release",
        "version": "0.3.2",
        "capture": "themes",
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
    parser.add_argument("--overlay21", type=Path, required=True)
    parser.add_argument("--overlay23", type=Path, required=True)
    parser.add_argument("--host21", type=Path, required=True)
    parser.add_argument("--host23", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package(**vars(args)))
