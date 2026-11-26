"""Check the exact dual-HW ZIP offline with two local qualified backups."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from package_capture_trial import SOURCE_KITS, digest, themes_kit

MANIFEST = "capture-trial-manifest.json"
SCRIPT = "Install-Capture.ps1"
NATIVE_ENTRY = "function Invoke-Native([string]$Program, [string[]]$ToolArgs) {\n"
# Insert only in a disposable copy. These are all the hardware commands. Any
# unrecognized command fails here, and only offline known commands run real code.
MOCK = r"""
    if (!(Test-Path Variable:script:mockScenario)) {
        $script:mockScenario = Read-Json $env:CAPTURE_MOCK_SCENARIO
        $script:mockInspects = 0
        $script:mockChecks = 0
    }
    $scenario = $script:mockScenario
    $command = if ($ToolArgs[0] -eq '--stock') { $ToolArgs[2] } else { $ToolArgs[0] }
    $hardware = Split-Path -Leaf (Split-Path -Parent $Program)
    $previous = if ($ToolArgs -contains '--previous-bundle') { $ToolArgs[[array]::IndexOf($ToolArgs, '--previous-bundle') + 1] } else { '' }
    Add-Content -LiteralPath $env:CAPTURE_MOCK_LOG -Value "$hardware,$command,$previous" -Encoding UTF8
    if ($scenario.fail_launch -ceq $command) {
        $Program += '.unavailable'
        $global:LASTEXITCODE = 0
    } else { switch ($command) {
        'inspect' {
            $index = [Math]::Min($script:mockInspects++, $scenario.inspects.Count - 1)
            return @{ Exit = $scenario.inspects[$index].exit; Lines = @($scenario.inspects[$index].lines) }
        }
        'stock' {
            $target = $ToolArgs[[array]::IndexOf($ToolArgs, '--output') + 1]
            Copy-Item -LiteralPath $scenario.stock -Destination $target -Recurse
            return @{ Exit = 0; Lines = @() }
        }
        'dfu-check' { return @{ Exit = 0; Lines = @() } }
        'check-device' {
            $target = $ToolArgs[[array]::IndexOf($ToolArgs, '--output') + 1]
            $index = [Math]::Min($script:mockChecks++, $scenario.checks.Count - 1)
            $check = $scenario.checks[$index]
            $null = [IO.Directory]::CreateDirectory($target)
            if ($check.report) {
                $check.report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'read-only.json') -Encoding UTF8
            }
            return @{ Exit = $check.exit; Lines = @() }
        }
        { $_ -in 'flash-probe', 'restore', 'cleanup-known-qr', 'start-probe', 'start-stock' } {
            return @{ Exit = $scenario.write_exit; Lines = @() }
        }
        { $_ -in 'verify', 'prepare', 'package-trial', 'audit' } { break }
        default { throw "Unexpected mock command $command" }
    } }
"""

SYSTEM = Path(os.environ["SystemRoot"]) / "System32"
PS = SYSTEM / "WindowsPowerShell/v1.0/powershell.exe"
CMD = SYSTEM / "cmd.exe"


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def inventory(folder):
    return {path.relative_to(folder): digest(path.read_bytes()) for path in folder.rglob("*") if path.is_file()}


def run(command, *, cwd, keyboard="", expected=0, **variables):
    env = dict(os.environ, PATH=str(SYSTEM), PSModulePath=str(PS.parent / "Modules"), **variables)
    result = subprocess.run([str(arg) for arg in command], cwd=cwd, env=env,
                            input=keyboard.encode("utf-8"), capture_output=True, timeout=45)
    if (result.returncode == 0) != (expected == 0):
        # Windows PowerShell 5.1 emits redirected text using the OEM code page.
        raw = result.stdout + result.stderr
        raise RuntimeError(raw.decode("oem", errors="replace"))
    return result.stdout


def powershell(kit, args, **kwargs):
    return run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", kit / SCRIPT, *args], cwd=kit, **kwargs)


def inspect(stock, *, mode="Application", wrong_port=False, hardware=None):
    manifest = load(stock / "manifest.json")
    port = manifest["usb_port"]
    identifier = json.dumps(port["bus_id"], ensure_ascii=False)
    chain = [*port["port_chain"], 1] if wrong_port else port["port_chain"]
    identity = manifest["identity"]
    hardware = hardware or identity["hardware"]
    firmware = "2.0.7" if mode == "Application" else ""
    serial = identity["serial"] if mode == "Application" else ""
    return {"exit": 0, "lines": [
        f"USB: {mode}; port Some(PortPath {{ bus_id: {identifier}, port_chain: {chain} }})",
        f'DeviceInfo {{ model: "KM003C", hw_version: "{hardware}", mfg_date: "2023/09/04", '
        f'fw_version: "{firmware}", fw_date: "", serial_id: "{serial}", uuid: "" }}',
    ]}


def state(label, sha256="a" * 64):
    return {
        "exit": int(label == "unknown-within-write-span"),
        "report": {"schema": 1, "mode": "Dfu", "state": label, "loader_matches": True,
                   "protected_neighbor_matches": True, "flash_writes": 0,
                   "reboot_sent": False, "internal_sha256": sha256},
    }


def write_manifest(kit):
    manifest_path = kit / MANIFEST
    manifest = load(manifest_path)
    raw = (kit / SCRIPT).read_bytes()
    record = next(entry for entry in manifest["files"] if entry["path"] == SCRIPT)
    record.update(bytes=len(raw), sha256=digest(raw))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test(archive, hw21_zip, hw23_zip, overlay21, overlay23, host21, host23, stock21, stock23, v1, prior23):
    original_inventories = [inventory(stock) for stock in (stock21, stock23)]
    if archive.with_suffix(".zip.sha256").read_text().split() != [digest(archive.read_bytes()), archive.name]:
        raise ValueError("ZIP checksum mismatch")
    with TemporaryDirectory(prefix="capture unified ") as staging:
        root = Path(staging)
        # Use both a space and non-ASCII characters in package/data paths.
        kit = root / "Windows kit \u65e5\u672c\u8a9e"
        with ZipFile(archive) as zip_file:
            manifest = json.loads(zip_file.read(MANIFEST))
            records = {entry["path"]: (entry["bytes"], entry["sha256"]) for entry in manifest["files"]}
            expected = {"Install.cmd", SCRIPT, "START-HERE.md", "START-HERE.ja.md", "LICENSE"}
            assert manifest["distribution"] == "release" and manifest["version"] == "0.3.2"
            assert zip_file.read(SCRIPT).decode("utf-8-sig").isascii()
            for key, source, overlay, host in (("hw21", hw21_zip, overlay21, host21),
                                                ("hw23", hw23_zip, overlay23, host23)):
                for name, raw in themes_kit(key, source, overlay, host).items():
                    expected.add(name)
                    assert zip_file.read(name) == raw
            assert manifest["source_kits"] == {key: value[0] for key, value in SOURCE_KITS.items()}
            assert expected == set(records) and len(zip_file.namelist()) == len(expected) + 1
            assert set(zip_file.namelist()) == expected | {MANIFEST}
            for name in expected:
                raw = zip_file.read(name)
                assert records[name] == (len(raw), digest(raw))
            zip_file.extractall(kit)
        run([CMD, "/d", "/c", "Install.cmd", "-CheckPackage"], cwd=kit)
        menu = powershell(kit, [], keyboard="0\n")
        assert b"KM003C Screen Capture v0.3.2" in menu
        assert b"2  Install or update using an existing backup" in menu
        gate = kit / "hw21/overlay/gate.bin"
        original_gate = gate.read_bytes()
        try:
            gate.write_bytes(bytes([original_gate[0] ^ 1]) + original_gate[1:])
            powershell(kit, ["-CheckPackage"], expected=1)
        finally:
            gate.write_bytes(original_gate)

        outputs = root / "recovery output \u65e5\u672c\u8a9e"
        # Test exact shipped scripts and binaries without replacing any code.
        powershell(kit, ["-Action", "Prepare", "-BackupPath", stock21.parent, "-DataDirectory", outputs])
        powershell(kit, ["-Action", "Prepare", "-BackupPath", stock23, "-DataDirectory", outputs])
        for prefix, relative in (("hw2.1-", "prepared/bundle.json"), ("hw2.3-", "prepared/bundle/bundle.json")):
            assert (next(outputs.glob(prefix + "*")) / relative).is_file()
        powershell(kit, ["-Action", "Prepare", "-BackupPath", root, "-DataDirectory", outputs], expected=1)
        powershell(kit, ["-Action", "Prepare", "-BackupPath", stock21, "-DataDirectory", stock21], expected=1)
        print("Package, Windows launcher, real offline preparation and backup path checks passed.")

        # Get exact old installed-image hashes from the actual bundled host.
        prior21 = {}
        for version, assets in (("boot-v4", "overlay-boot-v4"),
                                ("boot-numberless", "overlay-previous"), ("boot-v2", "overlay-boot-v2"),
                                ("boot-v3", "overlay-boot-v3")):
            output = root / version
            run([kit / "hw21/km003c-overlay-host.exe", "--stock", stock21, "package-trial",
                 "--overlay", kit / "hw21" / assets, "--output", output], cwd=kit)
            prior21[version] = digest((output / "expected-overlay-internal.bin").read_bytes())
        # Independently recreate the installed HW2.1 v4 image with the exact public v1.
        assert digest(v1.read_bytes()) == "31ddc18562105fba9fb67432721836fb65b674cdc1cb1577b66628af46502e38"
        with ZipFile(v1) as old_zip:
            old_zip.extractall(root / "public-v1")
        old_kit = root / "public-v1/hw21"
        run([old_kit / "km003c-overlay-host.exe", "--stock", stock21, "package-trial",
             "--overlay", old_kit / "overlay", "--output", root / "public-v1-overlay"], cwd=kit)
        assert prior21["boot-v4"] == digest((root / "public-v1-overlay/expected-overlay-internal.bin").read_bytes())
        audit_hash23 = digest((prior23 / "expected-overlay-internal.bin").read_bytes())

        path = kit / SCRIPT
        text = path.read_text(encoding="utf-8-sig")
        assert text.count(NATIVE_ENTRY) == 1
        path.write_text(text.replace(NATIVE_ENTRY, NATIVE_ENTRY + MOCK), encoding="utf-8-sig")
        write_manifest(kit)
        scenario_path = root / "scenario.json"
        log = root / "calls.txt"
        mock_output = root / "mock-runs"

        def scenario(name, keyboard, *, stock=stock21, inspects=None, checks=(), expected=0,
                     write_exit=0, fail_launch=""):
            log.unlink(missing_ok=True)
            scenario_path.write_text(json.dumps({
                "stock": str(stock),
                "inspects": inspects or [inspect(stock), inspect(stock, mode="Dfu")],
                "checks": list(checks), "write_exit": write_exit, "fail_launch": fail_launch,
            }), encoding="ascii")
            powershell(kit, ["-DataDirectory", mock_output], keyboard=keyboard, expected=expected,
                       CAPTURE_MOCK_SCENARIO=str(scenario_path), CAPTURE_MOCK_LOG=str(log))
            calls = [line.split(",", 2) for line in log.read_text(encoding="utf-8-sig").splitlines()] if log.exists() else []
            print(name)
            return calls

        update21 = f'2\n\n"{stock21.parent}"\nROM4MB\n\n'
        update23 = f"2\n\n{stock23}\n\n"
        mutations = {"stock", "flash-probe", "restore", "cleanup-known-qr", "start-probe", "start-stock"}
        for version, sha in prior21.items():
            calls = scenario("HW2.1 recognized legacy " + version, update21 + "INSTALL\n",
                             checks=[state("unknown-within-write-span", sha)])
            assert [(hw, command, Path(prev).name if prev else "") for hw, command, prev in calls if command in mutations] == [
                ("hw21", "flash-probe", version), ("hw21", "start-probe", "")]
        calls = scenario("HW2.3 recognizes the installed v0.3.1 without a previous bundle", update23 + "INSTALL\n",
                         stock=stock23, checks=[state("unknown-within-write-span", audit_hash23)])
        assert [(hw, command) for hw, command, _ in calls if command in mutations] == [
            ("hw23", "flash-probe"), ("hw23", "start-probe")]
        assert next(Path(prev).parent.name for _, command, prev in calls if command == "flash-probe") == "capture-0.3.1"
        for stock, keyboard, hardware in ((stock21, update21, "hw21"), (stock23, update23, "hw23")):
            calls = scenario(hardware + " skips same-version flash", keyboard, stock=stock, checks=[state("overlay-probe")])
            assert [(hw, command) for hw, command, _ in calls if command in mutations] == [(hardware, "start-probe")]

        serial23 = load(stock23 / "manifest.json")["identity"]["serial"]
        calls = scenario("HW2.3 fresh install, with DFU qualification before write",
                         f"1\n\n{serial23}\n\nINSTALL\n", stock=stock23, checks=[state("original-stock")])
        assert [command for _, command, _ in calls if command in mutations | {"dfu-check"}] == [
            "stock", "dfu-check", "flash-probe", "start-probe"]
        calls = scenario("Stock restore performs preserved backend flow", f"3\n\n{stock21}\n\nCLEARED\nRESTORE\n",
                         checks=[state("overlay-probe")])
        assert [command for _, command, _ in calls if command in mutations] == ["restore", "start-stock"]
        calls = scenario("Known HW2.1 QR repair requires its own confirmation",
                         f"5\n\n{stock21}\n\nCLEAN-QR\n", checks=[state("stock-with-known-qr-residue")])
        assert [command for _, command, _ in calls if command in mutations] == ["cleanup-known-qr", "start-stock"]

        for name, keyboard, options in (
            ("Wrong backup folder", f"2\n\n{root}\n", {}),
            ("No new backup on blank input", "2\n\n\n", {}),
            ("Wrong HW backup", update21, {"inspects": [inspect(stock23)]}),
            ("Unsupported HW2.5", update21, {"inspects": [inspect(stock21, hardware="2.5")]}),
            ("Multiple attached devices", update21, {"inspects": [{"exit": 1, "lines": ["multiple attached"]}]}),
            ("Wrong DFU port", update21, {"inspects": [inspect(stock21), inspect(stock21, mode="Dfu", wrong_port=True)]}),
            ("Port changed after confirmation", update21 + "INSTALL\n", {
                "inspects": [inspect(stock21), inspect(stock21, mode="Dfu"), inspect(stock21, mode="Dfu", wrong_port=True)],
                "checks": [state("original-stock")]}),
            ("Unknown internal image", update21, {"checks": [state("unknown-within-write-span")]}),
            ("Read failure without evidence", update21, {"checks": [{"exit": 1, "report": None}]}),
            ("Unconfirmed write", update21 + "cancel\n", {"checks": [state("original-stock")]}),
            ("Missing ROM confirmation", f"2\n\n{stock21}\n\n", {}),
        ):
            calls = scenario(name, keyboard, expected=1, **options)
            assert not (mutations & {command for _, command, _ in calls})
        calls = scenario("Failed transfer stops before start and is never retried", update21 + "INSTALL\n",
                         checks=[state("original-stock")], expected=1, write_exit=1)
        assert [command for _, command, _ in calls if command in mutations] == ["flash-probe"]
        calls = scenario("Backend launch failure cannot reuse an earlier success code", update21 + "INSTALL\n",
                         checks=[state("original-stock")], expected=1, fail_launch="flash-probe")
        assert [command for _, command, _ in calls if command in mutations] == ["flash-probe"]
    assert original_inventories == [inventory(stock) for stock in (stock21, stock23)]
    print("PASS: stock-free package, Windows 5.1, real offline backup/bundle audits, mocked USB/write flow, originals unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("archive", "hw21-zip", "hw23-zip", "overlay21", "overlay23", "host21",
                 "host23", "stock21", "stock23", "v1", "prior23"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    test(*(path.resolve(strict=True) for path in vars(args).values()))
