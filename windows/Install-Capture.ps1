# SPDX-License-Identifier: MIT
param(
    [ValidateSet('Menu', 'Prepare')][string]$Action = 'Menu',
    [string]$BackupPath,
    [string]$DataDirectory,
    [switch]$CheckPackage
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

$profiles = @{
    '2.1' = @{ Directory = 'hw21'; Overlay = 'overlay' }
    '2.3' = @{ Directory = 'hw23'; Overlay = 'overlays/screen-themes' }
}
$prior21 = [ordered]@{
    'boot-v4' = 'overlay-boot-v4'
    'boot-numberless' = 'overlay-previous'
    'boot-v2' = 'overlay-boot-v2'
    'boot-v3' = 'overlay-boot-v3'
}

function Read-Json([string]$Path) {
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Assert-Package {
    $manifest = Read-Json (Join-Path $PSScriptRoot 'capture-trial-manifest.json')
    if ($manifest.schema -ne 1 -or $manifest.stock_free -ne $true -or $manifest.firmware -cne '2.0.7') {
        throw 'The package manifest is invalid.'
    }
    $seen = @{}
    foreach ($entry in $manifest.files) {
        $name = [string]$entry.path
        if ($name -cnotmatch '^[A-Za-z0-9_.+-]+(/[A-Za-z0-9_.+-]+)*$' -or $name -match '(^|/)\.{1,2}(/|$)' -or $seen.ContainsKey($name)) {
            throw 'The package manifest contains an invalid filename.'
        }
        $path = Join-Path $PSScriptRoot $name
        $item = Get-Item -LiteralPath $path
        if ($item.PSIsContainer -or $item.Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $path).Hash -ine $entry.sha256) {
            throw "Package file changed ($name). Extract the ZIP again into a new folder."
        }
        $seen[$name] = $true
    }
    $required = @('Install.cmd', 'Install-Capture.ps1',
        'hw23/overlays/screen/gate.bin', 'hw23/overlays/screen/extension.bin')
    foreach ($profile in $profiles.Values) {
        foreach ($file in @('km003c-backup.exe', 'km003c-overlay-host.exe',
                "$($profile.Overlay)/gate.bin", "$($profile.Overlay)/extension.bin")) {
            $required += "$($profile.Directory)/$file"
        }
    }
    foreach ($overlay in $prior21.Values) {
        $required += @("hw21/$overlay/gate.bin", "hw21/$overlay/extension.bin")
    }
    foreach ($name in $required) {
        if (!$seen.ContainsKey($name)) { throw "Missing required package file $name." }
    }
    Write-Host 'KM003C Screen Capture v0.3.2 / stock FW 2.0.7 / HW 2.1 and 2.3'
}

function Invoke-Native([string]$Program, [string[]]$ToolArgs) {
    $ErrorActionPreference = 'Continue'
    # A failure to launch a process can leave PowerShell's previous exit code intact.
    $global:LASTEXITCODE = -1
    $lines = @(& $Program @ToolArgs 2>&1 | ForEach-Object { $_.ToString() })
    @{ Exit = $global:LASTEXITCODE; Lines = $lines }
}

function Use-Backend($Profile, [string]$Tool, [string[]]$ToolArgs) {
    $program = Join-Path $PSScriptRoot "$($Profile.Directory)/km003c-$Tool.exe"
    $result = Invoke-Native $program $ToolArgs
    foreach ($line in $result.Lines) { Write-Host $line }
    if ($result.Exit -ne 0) { throw "$Tool stopped with exit code $($result.Exit)." }
}

function Get-ConnectedMeter {
    # Both released backup executables use this inspect implementation. Adapt its
    # pinned two-line output here and pass structured identity to the dispatcher.
    $program = Join-Path $PSScriptRoot 'hw23/km003c-backup.exe'
    $result = Invoke-Native $program @('inspect')
    if ($result.Exit -ne 0) {
        foreach ($line in $result.Lines) { Write-Host $line }
        throw 'Could not identify the meter. Connect one meter via its side USB port. If it shows USB SCREENSHOTS, disconnect and reconnect without holding any buttons.'
    }
    if ($result.Lines.Count -ne 2) { throw 'The meter information has an unexpected format.' }
    $usb = [regex]::Match($result.Lines[0], '^USB: (Application|Dfu); port Some\(PortPath \{ bus_id: ("(?:[^"\\]|\\.)+"), port_chain: \[([0-9]+(?:, [0-9]+)*)\] \}\)$')
    $info = [regex]::Match($result.Lines[1], '^DeviceInfo \{ model: "KM003C", hw_version: "([0-9.]+)", mfg_date: "(?:[^"\\]|\\.)*", fw_version: "([0-9.]*)", fw_date: "(?:[^"\\]|\\.)*", serial_id: "([A-Za-z0-9]*)", uuid: "(?:[^"\\]|\\.)*" \}$')
    if (!$usb.Success -or !$info.Success) { throw 'Could not verify the meter information or physical USB port.' }
    $hardware = $info.Groups[1].Value
    if (!$profiles.ContainsKey($hardware)) { throw "HW $hardware is unsupported." }
    $bus = ('{"id":' + $usb.Groups[2].Value + '}') | ConvertFrom-Json
    @{
        Mode = $usb.Groups[1].Value
        Hardware = $hardware
        Firmware = $info.Groups[2].Value
        Serial = $info.Groups[3].Value
        Bus = [string]$bus.id
        Ports = $usb.Groups[3].Value -replace ', ', ','
    }
}

function Resolve-RecordFolder([string]$Path, [string]$Child, [string]$Marker) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'Specify an existing folder.' }
    $resolved = Get-Item -LiteralPath ($Path.Trim().Trim('"'))
    if (!$resolved.PSIsContainer -or $resolved.PSProvider.Name -ne 'FileSystem') {
        throw 'Specify the path to an existing folder.'
    }
    $parent = $resolved.FullName
    $nested = Join-Path $parent $Child
    $candidates = @(@($parent, $nested) | Where-Object { Test-Path -LiteralPath (Join-Path $_ $Marker) -PathType Leaf })
    if ($candidates.Count -ne 1) { throw "Select the folder containing $Marker or its immediate parent." }
    $candidates[0]
}

function Get-Backup([string]$Path) {
    $stock = Resolve-RecordFolder $Path 'stock' 'manifest.json'
    $manifest = Read-Json (Join-Path $stock 'manifest.json')
    $hardware = [string]$manifest.identity.hardware
    if ($manifest.identity.model -cne 'KM003C' -or $manifest.identity.firmware -cne '2.0.7' -or !$profiles.ContainsKey($hardware)) {
        throw 'This backup is incompatible with the supported KM003C profiles.'
    }
    $profile = $profiles[$hardware]
    Use-Backend $profile 'backup' @('verify', '--stock', $stock, '--require-dfu')
    @{ Stock = $stock; Manifest = $manifest; Hardware = $hardware; Profile = $profile }
}

function Assert-MeterMatches($Meter, $Record, [string]$RequiredMode) {
    $saved = $Record.Manifest
    if ($Meter.Mode -cne $RequiredMode) { throw "The meter must be in $RequiredMode mode for this step." }
    if ($Meter.Hardware -cne $Record.Hardware -or $Meter.Bus -cne $saved.usb_port.bus_id -or
            $Meter.Ports -cne ($saved.usb_port.port_chain -join ',')) {
        throw 'The hardware revision or USB port differs from the backup. Use the same meter and PC USB port used to make the backup.'
    }
    if (($Meter.Mode -eq 'Application' -and ($Meter.Firmware -cne '2.0.7' -or !$Meter.Serial)) -or
            ($Meter.Serial -and $Meter.Serial -cne $saved.identity.serial)) {
        throw 'The meter identity differs from the backup.'
    }
}

function Confirm-Rom([string]$Hardware) {
    if ($Hardware -ceq '2.1') {
        if ((Read-Host 'Check ROM capacity in Device information or POWER-Z Lab. Type ROM4MB only if it shows 4 MB') -cne 'ROM4MB') {
            throw 'HW 2.1 requires confirmation of 4 MB ROM.'
        }
    }
}

function Enter-Dfu {
    $null = Read-Host 'Unplug the side USB cable. When the screen goes dark, hold Exit only and reconnect to the same PC port. At BOOT Loader, release Exit and press Enter'
}

function New-Session([string]$Hardware, [string]$ExistingStock) {
    $root = if ($DataDirectory) { [IO.Path]::GetFullPath($DataDirectory) } else {
        Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'KM003C Capture Installer'
    }
    if ($ExistingStock) {
        $existing = $ExistingStock.TrimEnd('\', '/') + '\'
        if (($root.TrimEnd('\', '/') + '\').StartsWith($existing, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Choose an output location outside the existing stock backup.'
        }
    }
    $name = 'hw{0}-{1}-{2}' -f $Hardware, (Get-Date -Format 'yyyyMMdd-HHmmss'), [guid]::NewGuid().ToString('N').Substring(0, 8)
    $path = Join-Path $root $name
    $null = [IO.Directory]::CreateDirectory($path)
    Write-Host "Logs and recovery data for this meter are stored at $path"
    $path
}

function New-CaptureBundle($Record, [string]$Output, [string]$Overlay, [string]$Variant = 'screen-themes') {
    $profile = $Record.Profile
    $assets = Join-Path $PSScriptRoot "$($profile.Directory)/$Overlay"
    if ($Record.Hardware -ceq '2.1') {
        Use-Backend $profile 'overlay-host' @('--stock', $Record.Stock, 'package-trial', '--overlay', $assets, '--output', $Output)
        $bundle = $Output
    } else {
        Use-Backend $profile 'overlay-host' @('--stock', $Record.Stock, 'prepare', '--variant', $Variant, '--overlay', $assets, '--output', $Output)
        $bundle = Join-Path $Output 'bundle'
    }
    Use-Backend $profile 'overlay-host' @('--stock', $Record.Stock, 'audit', '--bundle', $bundle)
    $bundle
}

function Read-DeviceState($Record, [string]$Bundle, [string]$Output) {
    $program = Join-Path $PSScriptRoot "$($Record.Profile.Directory)/km003c-overlay-host.exe"
    $result = Invoke-Native $program @('--stock', $Record.Stock, 'check-device', '--bundle', $Bundle, '--output', $Output)
    $path = Join-Path $Output 'read-only.json'
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) {
        foreach ($line in $result.Lines) { Write-Host $line }
        throw 'The read-only verification did not complete.'
    }
    $report = Read-Json $path
    $knownStates = @('original-stock', 'overlay-probe', 'rollback-erase-pass', 'stock-with-known-qr-residue')
    $validState = ($result.Exit -eq 0 -and $report.state -cin $knownStates) -or
        ($result.Exit -eq 1 -and $report.state -ceq 'unknown-within-write-span')
    if (!$validState -or $report.schema -ne 1 -or $report.mode -cne 'Dfu' -or $report.loader_matches -ne $true -or
            $report.protected_neighbor_matches -ne $true -or $report.flash_writes -ne 0 -or
            $report.reboot_sent -ne $false -or $report.internal_sha256 -cnotmatch '^[a-f0-9]{64}$') {
        throw 'Could not verify the DFU readback.'
    }
    $report
}

function Find-PreviousBundle($Record, $State, [string]$Session) {
    if ($Record.Hardware -ceq '2.1') {
        $matched = @(
            foreach ($version in $prior21.Keys) {
                $prior = New-CaptureBundle $Record (Join-Path $Session $version) $prior21[$version]
                if ((Get-FileHash -LiteralPath (Join-Path $prior 'expected-overlay-internal.bin')).Hash -ieq $State.internal_sha256) {
                    $prior
                }
            }
        )
        if ($matched.Count -ne 1) { throw 'Internal flash did not match a single known HW 2.1 capture build.' }
        Write-Host "Full internal flash matches the previous build $(Split-Path -Leaf $matched[0])."
        return $matched[0]
    }
    $release031 = New-CaptureBundle $Record (Join-Path $Session 'capture-0.3.1') 'overlays/screen' 'screen'
    if ((Get-FileHash -LiteralPath (Join-Path $release031 'expected-overlay-internal.bin')).Hash -ieq $State.internal_sha256) {
        Write-Host 'Full internal flash matches the previous build capture-0.3.1.'
        return $release031
    }
    $previous = Resolve-RecordFolder (Read-Host 'Enter the bundle folder used to install the current extension, or its parent') 'bundle' 'bundle.json'
    Use-Backend $Record.Profile 'overlay-host' @('--stock', $Record.Stock, 'audit', '--bundle', $previous)
    $priorState = Read-DeviceState $Record $previous (Join-Path $Session 'check-previous')
    if ($priorState.state -cne 'overlay-probe' -or $priorState.internal_sha256 -cne $State.internal_sha256) {
        throw 'Internal flash does not match the supplied previous bundle.'
    }
    $previous
}

function Confirm-Write([string]$Word) {
    if ((Read-Host "A failed flash can prevent the meter from starting. Save your backup and type $Word to continue") -cne $Word) {
        throw 'Flash operation canceled.'
    }
}

Assert-Package
if ($CheckPackage) { exit 0 }
if (![Environment]::Is64BitOperatingSystem -or ![Environment]::Is64BitProcess) {
    throw 'Use 64-bit Windows and 64-bit Windows PowerShell.'
}
$operation = $Action
if ($operation -eq 'Menu') {
    Write-Host '1  First install from stock firmware'
    Write-Host '2  Install or update using an existing backup'
    Write-Host '3  Restore stock firmware'
    Write-Host '4  Identify connected meter (read-only)'
    Write-Host '5  Recover from known HW 2.1 QR remnants'
    Write-Host '6  Verify an existing backup and prepare files (offline)'
    Write-Host '0  Exit'
    $operation = switch -CaseSensitive (Read-Host 'Select an operation') {
        '0' { exit 0 }
        '1' { 'Fresh' }
        '2' { 'Update' }
        '3' { 'Restore' }
        '4' { 'Inspect' }
        '5' { 'CleanupQr' }
        '6' { 'Prepare' }
        default { throw 'Choose a number from 0 to 6.' }
    }
}

# Offline preparation needs no USB lock. Serialize the device operations in this tool.
$mutex = $null
$locked = $false
try {
    if ($operation -ne 'Prepare') {
        $mutex = [Threading.Mutex]::new($false, 'Local\KM003C-Capture-Installer')
        try { $locked = $mutex.WaitOne(0) }
        catch [Threading.AbandonedMutexException] { $locked = $true }
        if (!$locked) { throw 'Another instance of the capture installer is running.' }
        $null = Read-Host 'Close MTools and any other installer. Leave both measurement ports empty, connect the side USB port only, then press Enter'
    }
    if ($operation -eq 'Inspect') {
        $meter = Get-ConnectedMeter
        Write-Host "KM003C HW $($meter.Hardware) / FW $($meter.Firmware) / $($meter.Mode)"
        return
    }

    if ($operation -eq 'Fresh') {
        $meter = Get-ConnectedMeter
        if ($meter.Mode -cne 'Application' -or $meter.Firmware -cne '2.0.7' -or !$meter.Serial) {
            throw 'For a first install, start the meter normally with unmodified stock FW 2.0.7.'
        }
        Write-Host "Detected meter HW $($meter.Hardware) / serial $($meter.Serial)"
        if ((Read-Host 'Type the displayed serial exactly to create the initial stock backup') -cne $meter.Serial) {
            throw 'The entered serial number did not match.'
        }
        Confirm-Rom $meter.Hardware
        $session = New-Session $meter.Hardware
        $stock = Join-Path $session 'stock'
        $profile = $profiles[$meter.Hardware]
        Use-Backend $profile 'backup' @('stock', '--serial', $meter.Serial, '--output', $stock)
        $beforeDfu = @{ Manifest = (Read-Json (Join-Path $stock 'manifest.json')); Hardware = $meter.Hardware }
        Assert-MeterMatches $meter $beforeDfu 'Application'
        Enter-Dfu
        Assert-MeterMatches (Get-ConnectedMeter) $beforeDfu 'Dfu'
        Use-Backend $profile 'backup' @('dfu-check', '--stock', $stock)
        $record = Get-Backup $stock
    } else {
        if (!$BackupPath) { $BackupPath = Read-Host 'Enter the original stock backup folder or its immediate parent' }
        $record = Get-Backup $BackupPath
        if ($operation -eq 'CleanupQr' -and $record.Hardware -cne '2.1') { throw 'QR remnant recovery requires HW 2.1.' }
        if ($operation -ne 'Prepare') {
            $meter = Get-ConnectedMeter
            if ($operation -eq 'Restore' -and $meter.Mode -ceq 'Dfu') {
                Assert-MeterMatches $meter $record 'Dfu'
                if ((Read-Host 'If the meter cannot start normally, verify it is the unit from the backup on the same PC port, then type DFU') -cne 'DFU') {
                    throw 'DFU restore canceled.'
                }
            } else {
                Assert-MeterMatches $meter $record 'Application'
            }
            if ($operation -eq 'Update') { Confirm-Rom $record.Hardware }
        }
        $session = New-Session $record.Hardware $record.Stock
    }
    Write-Host "Using stock backup $($record.Stock)"
    $profile = $record.Profile
    $bundle = New-CaptureBundle $record (Join-Path $session 'prepared') $profile.Overlay
    Write-Host "HW $($record.Hardware) Screen Capture / Verified installation and recovery files at $bundle"
    if ($operation -eq 'Prepare') { return }

    if ($operation -ne 'Fresh' -and $meter.Mode -ceq 'Application') {
        if ($operation -eq 'Restore') {
            Write-Host 'Before restoring from capture firmware, copy out your BMPs, clear captures with the installed capture firmware, then start normally.'
        } elseif ($operation -eq 'Update') {
            Write-Host 'Copy any BMPs you want to keep before updating. You can keep the captures on the meter during an update.'
        }
        Enter-Dfu
    }
    Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
    $state = Read-DeviceState $record $bundle (Join-Path $session 'check')
    Write-Host "Read-only verification result $($state.state)"
    $hostArgs = @('--stock', $record.Stock)
    $bundleArgs = @('--bundle', $bundle)

    if ($operation -eq 'CleanupQr') {
        if ($state.state -cne 'stock-with-known-qr-residue') { throw 'Known QR remnants were not verified for this meter and backup.' }
        Confirm-Write 'CLEAN-QR'
        Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
        Use-Backend $profile 'overlay-host' ($hostArgs + @('cleanup-known-qr') + $bundleArgs + @('--output', (Join-Path $session 'cleanup')))
    } elseif ($operation -eq 'Restore') {
        $storage = Read-Host 'Type CLEARED if stock firmware is installed or capture storage is confirmed empty. If the meter cannot boot and you cannot verify storage, type EMERGENCY'
        if ($storage -cne 'CLEARED' -and $storage -cne 'EMERGENCY') { throw 'Stock restore canceled.' }
        if ($state.state -ceq 'unknown-within-write-span') {
            Write-Host 'Unknown data was detected within the writable flash region. Confirm the stock restore to recover this region from the backup.'
        }
        Confirm-Write 'RESTORE'
        Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
        Use-Backend $profile 'overlay-host' ($hostArgs + @('restore') + $bundleArgs + @('--output', (Join-Path $session 'restore')))
    } else {
        $previous = $null
        switch -CaseSensitive ($state.state) {
            'original-stock' {}
            'overlay-probe' {
                if ($operation -eq 'Fresh') { throw 'First install requires unmodified stock firmware.' }
                Write-Host 'This build is already installed. Skipping flash writes.'
            }
            'stock-with-known-qr-residue' { throw 'Known QR remnants detected. Run menu option 5 before installing again.' }
            'rollback-erase-pass' { throw 'A stock restore is incomplete. Run menu option 3 to finish restoring stock firmware.' }
            'unknown-within-write-span' {
                if ($operation -eq 'Fresh') { throw 'The meter does not match the stock state required for a first install.' }
                $previous = Find-PreviousBundle $record $state $session
            }
            default { throw 'Could not verify the installed firmware.' }
        }
        if ($state.state -cne 'overlay-probe') {
            Confirm-Write 'INSTALL'
            Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
            $flashArgs = $hostArgs + @('flash-probe') + $bundleArgs + @('--output', (Join-Path $session 'install'))
            if ($previous) { $flashArgs += @('--previous-bundle', $previous) }
            Use-Backend $profile 'overlay-host' $flashArgs
        }
        Use-Backend $profile 'overlay-host' ($hostArgs + @('start-probe') + $bundleArgs + @('--output', (Join-Path $session 'start')))
        Write-Host 'On the normal screen, press Left and Right together to capture. To copy BMPs, reconnect the side USB cable while holding only Left and Right.'
        return
    }
    Use-Backend $profile 'overlay-host' ($hostArgs + @('start-stock') + $bundleArgs + @('--output', (Join-Path $session 'start-stock')))
    Write-Host 'Verify that the stock screen and measurement functions have returned.'
} catch {
    Write-Host 'Operation stopped. Keep your backup and logs, and review the error before retrying.'
    throw
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
