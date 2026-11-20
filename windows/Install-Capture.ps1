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
    '2.1' = @{ Directory = 'hw21'; Version = 'v4'; Overlay = 'overlay' }
    '2.3' = @{ Directory = 'hw23'; Version = '0.3.1'; Overlay = 'overlays/screen' }
}
$prior21 = [ordered]@{
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
        throw '試験ZIPのマニフェストが一致しません。'
    }
    $seen = @{}
    foreach ($entry in $manifest.files) {
        $name = [string]$entry.path
        if ($name -cnotmatch '^[A-Za-z0-9_.+-]+(/[A-Za-z0-9_.+-]+)*$' -or $name -match '(^|/)\.{1,2}(/|$)' -or $seen.ContainsKey($name)) {
            throw '試験ZIPのファイル名が不正です。'
        }
        $path = Join-Path $PSScriptRoot $name
        $item = Get-Item -LiteralPath $path
        if ($item.PSIsContainer -or $item.Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $path).Hash -ine $entry.sha256) {
            throw "試験ZIPの内容が変わっています。新しいフォルダに展開し直してください。$name"
        }
        $seen[$name] = $true
    }
    $required = @('Install.cmd', 'Install-Capture.ps1')
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
        if (!$seen.ContainsKey($name)) { throw "試験ZIPの必須ファイルがありません。$name" }
    }
    Write-Host '統合キャプチャ試験版 / FW 2.0.7 / HW 2.1 v4・HW 2.3 0.3.1'
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
    if ($result.Exit -ne 0) { throw "処理を中止しました。$Tool (終了コード $($result.Exit))" }
}

function Get-ConnectedMeter {
    # Both released backup executables use this inspect implementation. Adapt its
    # pinned two-line output here and pass structured identity to the dispatcher.
    $program = Join-Path $PSScriptRoot 'hw23/km003c-backup.exe'
    $result = Invoke-Native $program @('inspect')
    if ($result.Exit -ne 0) {
        foreach ($line in $result.Lines) { Write-Host $line }
        throw '本体を確認できません。側面HIDで1台だけ接続してください。USB SCREENSHOTSが表示中なら通常起動で接続し直してください。'
    }
    if ($result.Lines.Count -ne 2) { throw '本体情報の形式を確認できません。' }
    $usb = [regex]::Match($result.Lines[0], '^USB: (Application|Dfu); port Some\(PortPath \{ bus_id: ("(?:[^"\\]|\\.)+"), port_chain: \[([0-9]+(?:, [0-9]+)*)\] \}\)$')
    $info = [regex]::Match($result.Lines[1], '^DeviceInfo \{ model: "KM003C", hw_version: "([0-9.]+)", mfg_date: "(?:[^"\\]|\\.)*", fw_version: "([0-9.]*)", fw_date: "(?:[^"\\]|\\.)*", serial_id: "([A-Za-z0-9]*)", uuid: "(?:[^"\\]|\\.)*" \}$')
    if (!$usb.Success -or !$info.Success) { throw 'KM003Cの本体情報または物理USBポートを確認できません。' }
    $hardware = $info.Groups[1].Value
    if (!$profiles.ContainsKey($hardware)) { throw "この試験版の対象外です。HW $hardware" }
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
    if ([string]::IsNullOrWhiteSpace($Path)) { throw '既存フォルダを指定してください。' }
    $resolved = Get-Item -LiteralPath ($Path.Trim().Trim('"'))
    if (!$resolved.PSIsContainer -or $resolved.PSProvider.Name -ne 'FileSystem') {
        throw 'ファイルではなく既存のフォルダを指定してください。'
    }
    $parent = $resolved.FullName
    $nested = Join-Path $parent $Child
    $candidates = @(@($parent, $nested) | Where-Object { Test-Path -LiteralPath (Join-Path $_ $Marker) -PathType Leaf })
    if ($candidates.Count -ne 1) { throw "対象フォルダを特定できません。$Marker のあるフォルダか、そのひとつ上を指定してください。" }
    $candidates[0]
}

function Get-Backup([string]$Path) {
    $stock = Resolve-RecordFolder $Path 'stock' 'manifest.json'
    $manifest = Read-Json (Join-Path $stock 'manifest.json')
    $hardware = [string]$manifest.identity.hardware
    if ($manifest.identity.model -cne 'KM003C' -or $manifest.identity.firmware -cne '2.0.7' -or !$profiles.ContainsKey($hardware)) {
        throw 'この試験版の対象となるKM003Cのバックアップではありません。'
    }
    $profile = $profiles[$hardware]
    Use-Backend $profile 'backup' @('verify', '--stock', $stock, '--require-dfu')
    @{ Stock = $stock; Manifest = $manifest; Hardware = $hardware; Profile = $profile }
}

function Assert-MeterMatches($Meter, $Record, [string]$RequiredMode) {
    $saved = $Record.Manifest
    if ($Meter.Mode -cne $RequiredMode) { throw '本体の接続モードが手順と一致しません。' }
    if ($Meter.Hardware -cne $Record.Hardware -or $Meter.Bus -cne $saved.usb_port.bus_id -or
            $Meter.Ports -cne ($saved.usb_port.port_chain -join ',')) {
        throw '本体のHWまたはUSBポートがバックアップと一致しません。バックアップ取得時と同じPC側ポートを使用してください。'
    }
    if (($Meter.Mode -eq 'Application' -and ($Meter.Firmware -cne '2.0.7' -or !$Meter.Serial)) -or
            ($Meter.Serial -and $Meter.Serial -cne $saved.identity.serial)) {
        throw '本体情報がバックアップと一致しません。'
    }
}

function Confirm-Rom([string]$Hardware) {
    if ($Hardware -ceq '2.1') {
        if ((Read-Host '本体情報またはPOWER-Z LabでROMが4MBと確認できた場合だけ ROM4MB と入力') -cne 'ROM4MB') {
            throw 'HW 2.1のROM容量確認が必要です。'
        }
    }
}

function Enter-Dfu {
    $null = Read-Host '側面HIDを抜き、画面が消えたらExitだけを押しながら同じPC側ポートへ再接続。BOOT Loaderが出たら離し、Enter'
}

function New-Session([string]$Hardware, [string]$ExistingStock) {
    $root = if ($DataDirectory) { [IO.Path]::GetFullPath($DataDirectory) } else {
        Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'KM003C Capture Installer'
    }
    if ($ExistingStock) {
        $existing = $ExistingStock.TrimEnd('\', '/') + '\'
        if (($root.TrimEnd('\', '/') + '\').StartsWith($existing, [StringComparison]::OrdinalIgnoreCase)) {
            throw '作業データの保存先には既存の純正バックアップの外を指定してください。'
        }
    }
    $name = 'hw{0}-{1}-{2}' -f $Hardware, (Get-Date -Format 'yyyyMMdd-HHmmss'), [guid]::NewGuid().ToString('N').Substring(0, 8)
    $path = Join-Path $root $name
    $null = [IO.Directory]::CreateDirectory($path)
    Write-Host "今回の記録と復旧データの保存先（個体データを含みます） $path"
    $path
}

function New-CaptureBundle($Record, [string]$Output, [string]$Overlay) {
    $profile = $Record.Profile
    $assets = Join-Path $PSScriptRoot "$($profile.Directory)/$Overlay"
    if ($Record.Hardware -ceq '2.1') {
        Use-Backend $profile 'overlay-host' @('--stock', $Record.Stock, 'package-trial', '--overlay', $assets, '--output', $Output)
        $bundle = $Output
    } else {
        Use-Backend $profile 'overlay-host' @('--stock', $Record.Stock, 'prepare', '--variant', 'screen', '--overlay', $assets, '--output', $Output)
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
        throw '読み取り照合が完了しませんでした。'
    }
    $report = Read-Json $path
    $knownStates = @('original-stock', 'overlay-probe', 'rollback-erase-pass', 'stock-with-known-qr-residue')
    $validState = ($result.Exit -eq 0 -and $report.state -cin $knownStates) -or
        ($result.Exit -eq 1 -and $report.state -ceq 'unknown-within-write-span')
    if (!$validState -or $report.schema -ne 1 -or $report.mode -cne 'Dfu' -or $report.loader_matches -ne $true -or
            $report.protected_neighbor_matches -ne $true -or $report.flash_writes -ne 0 -or
            $report.reboot_sent -ne $false -or $report.internal_sha256 -cnotmatch '^[a-f0-9]{64}$') {
        throw 'DFUでの読み取り結果を確認できません。'
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
        if ($matched.Count -ne 1) { throw 'HW 2.1の既知のキャプチャ試験版と一致しません。' }
        Write-Host "旧版と内部全体が一致しました。$(Split-Path -Leaf $matched[0])"
        return $matched[0]
    }
    $previous = Resolve-RecordFolder (Read-Host '現在の拡張版を導入したときの旧bundleフォルダ（またはその親）') 'bundle' 'bundle.json'
    Use-Backend $Record.Profile 'overlay-host' @('--stock', $Record.Stock, 'audit', '--bundle', $previous)
    $priorState = Read-DeviceState $Record $previous (Join-Path $Session 'check-previous')
    if ($priorState.state -cne 'overlay-probe' -or $priorState.internal_sha256 -cne $State.internal_sha256) {
        throw '指定の旧版と本体の内部状態が一致しません。'
    }
    $previous
}

function Confirm-Write([string]$Word) {
    if ((Read-Host "書き込みに失敗すると起動不能になる場合があります。バックアップを保管し、続ける場合は $Word と入力") -cne $Word) {
        throw '書き込みを取り消しました。'
    }
}

Assert-Package
if ($CheckPackage) { exit 0 }
if (![Environment]::Is64BitOperatingSystem -or ![Environment]::Is64BitProcess) {
    throw '64bit Windowsと64bit Windows PowerShellを使用してください。'
}
$operation = $Action
if ($operation -eq 'Menu') {
    Write-Host '1 初回導入（未改変の純正から）    2 既存バックアップから導入・更新'
    Write-Host '3 純正へ復元    4 本体確認（読取のみ）    5 HW 2.1の既知の旧QR残存を復旧'
    Write-Host '6 既存バックアップの検証と準備（USB不要）    0 終了'
    $operation = switch -CaseSensitive (Read-Host '操作を選択') {
        '0' { exit 0 }
        '1' { 'Fresh' }
        '2' { 'Update' }
        '3' { 'Restore' }
        '4' { 'Inspect' }
        '5' { 'CleanupQr' }
        '6' { 'Prepare' }
        default { throw '0〜6を選んでください。' }
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
        if (!$locked) { throw '別の統合キャプチャ導入ツールが実行中です。' }
        $null = Read-Host 'MTools・旧導入ツールを閉じ、測定用ポート2つを空け、側面HIDだけをつないでEnter'
    }
    if ($operation -eq 'Inspect') {
        $meter = Get-ConnectedMeter
        Write-Host "KM003C HW $($meter.Hardware) / FW $($meter.Firmware) / $($meter.Mode)"
        return
    }

    if ($operation -eq 'Fresh') {
        $meter = Get-ConnectedMeter
        if ($meter.Mode -cne 'Application' -or $meter.Firmware -cne '2.0.7' -or !$meter.Serial) {
            throw '初回導入は未改変の純正FW 2.0.7を通常起動して始めてください。'
        }
        Write-Host "検出した本体 HW $($meter.Hardware) / シリアル $($meter.Serial)"
        if ((Read-Host '純正初回バックアップを作成する本体のシリアルを表示のまま入力') -cne $meter.Serial) {
            throw '本体のシリアル確認が一致しません。'
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
        if (!$BackupPath) { $BackupPath = Read-Host '既存の stock フォルダ、またはそのひとつ上の親フォルダ' }
        $record = Get-Backup $BackupPath
        if ($operation -eq 'CleanupQr' -and $record.Hardware -cne '2.1') { throw '旧QR残存の復旧はHW 2.1専用です。' }
        if ($operation -ne 'Prepare') {
            $meter = Get-ConnectedMeter
            if ($operation -eq 'Restore' -and $meter.Mode -ceq 'Dfu') {
                Assert-MeterMatches $meter $record 'Dfu'
                if ((Read-Host '通常起動できず、バックアップを採った本体が同じポートにあると確認できる場合は DFU と入力') -cne 'DFU') {
                    throw 'DFUからの復元を取り消しました。'
                }
            } else {
                Assert-MeterMatches $meter $record 'Application'
            }
            if ($operation -eq 'Update') { Confirm-Rom $record.Hardware }
        }
        $session = New-Session $record.Hardware $record.Stock
    }
    Write-Host "使用する純正バックアップ $($record.Stock)"
    $profile = $record.Profile
    $bundle = New-CaptureBundle $record (Join-Path $session 'prepared') $profile.Overlay
    Write-Host "HW $($record.Hardware) キャプチャ $($profile.Version) / 照合済みの導入・復旧データ $bundle"
    if ($operation -eq 'Prepare') { return }

    if ($operation -ne 'Fresh' -and $meter.Mode -ceq 'Application') {
        if ($operation -eq 'Restore') {
            Write-Host 'キャプチャ版から純正へ戻す場合は、先にBMPを退避し、現在のキャプチャ版で画像を消去して通常起動へ戻してください。'
        } elseif ($operation -eq 'Update') {
            Write-Host '必要なBMPは更新前にPCへ退避してください。キャプチャ版の更新に画像消去は不要です。'
        }
        Enter-Dfu
    }
    Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
    $state = Read-DeviceState $record $bundle (Join-Path $session 'check')
    Write-Host "読み取り照合結果 $($state.state)"
    $hostArgs = @('--stock', $record.Stock)
    $bundleArgs = @('--bundle', $bundle)

    if ($operation -eq 'CleanupQr') {
        if ($state.state -cne 'stock-with-known-qr-residue') { throw 'この本体とバックアップで既知の旧QR残存を確認できません。' }
        Confirm-Write 'CLEAN-QR'
        Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
        Use-Backend $profile 'overlay-host' ($hostArgs + @('cleanup-known-qr') + $bundleArgs + @('--output', (Join-Path $session 'cleanup')))
    } elseif ($operation -eq 'Restore') {
        $storage = Read-Host '純正または画像保存領域の消去を確認済みなら CLEARED、本体が起動せず確認できない場合は EMERGENCY と入力'
        if ($storage -cne 'CLEARED' -and $storage -cne 'EMERGENCY') { throw '純正への復元を取り消しました。' }
        if ($state.state -ceq 'unknown-within-write-span') {
            Write-Host '書き込み許可範囲に識別できない内容があります。純正復元を選択した場合だけ既存の復旧処理でその範囲を戻します。'
        }
        Confirm-Write 'RESTORE'
        Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
        Use-Backend $profile 'overlay-host' ($hostArgs + @('restore') + $bundleArgs + @('--output', (Join-Path $session 'restore')))
    } else {
        $previous = $null
        switch -CaseSensitive ($state.state) {
            'original-stock' {}
            'overlay-probe' {
                if ($operation -eq 'Fresh') { throw '初回導入は未改変の純正から実行してください。' }
                Write-Host '同じ版が入っています。フラッシュ書き込みは省略します。'
            }
            'stock-with-known-qr-residue' { throw '既知の旧QR残存を確認しました。メニュー5で復旧してから、もう一度導入してください。' }
            'rollback-erase-pass' { throw '復元途中の状態です。メニュー3で純正への復元を完了させてください。' }
            'unknown-within-write-span' {
                if ($operation -eq 'Fresh') { throw '初回導入に必要な純正状態と一致しません。' }
                $previous = Find-PreviousBundle $record $state $session
            }
            default { throw '更新元の状態を確認できません。' }
        }
        if ($state.state -cne 'overlay-probe') {
            Confirm-Write 'INSTALL'
            Assert-MeterMatches (Get-ConnectedMeter) $record 'Dfu'
            $flashArgs = $hostArgs + @('flash-probe') + $bundleArgs + @('--output', (Join-Path $session 'install'))
            if ($previous) { $flashArgs += @('--previous-bundle', $previous) }
            Use-Backend $profile 'overlay-host' $flashArgs
        }
        Use-Backend $profile 'overlay-host' ($hostArgs + @('start-probe') + $bundleArgs + @('--output', (Join-Path $session 'start')))
        Write-Host '通常画面で左右同時押しで撮影し、左右だけを押しながら側面HIDをつなぎ直してUSBドライブからBMPを取り出してください。'
        return
    }
    Use-Backend $profile 'overlay-host' ($hostArgs + @('start-stock') + $bundleArgs + @('--output', (Join-Path $session 'start-stock')))
    Write-Host '純正画面と測定機能が戻ったことを確認してください。'
} catch {
    Write-Host '処理を中断しました。自動再試行は行いません。バックアップと記録を保管してください。'
    throw
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
