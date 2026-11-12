param([switch]$CheckPackage, [string]$DataDirectory)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$packageRoot = $PSScriptRoot

function Assert-Package {
    $manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'release-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or !$manifest.stock_free -or $manifest.files.Count -lt 6) { throw 'Invalid release manifest' }
    $seen = @{}
    foreach ($entry in $manifest.files) {
        $name = [string]$entry.path
        if ($name -match '(^/|\\|(^|/)\.\.(/|$)|:)' -or $seen.ContainsKey($name)) { throw 'Invalid release path' }
        $seen[$name] = $true
        $path = Join-Path $packageRoot $name
        $item = Get-Item -LiteralPath $path
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $hash = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($path))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
        if ($item.PSIsContainer -or $item.Length -ne $entry.bytes -or $hash -ne $entry.sha256) {
            throw "Package file changed: $name. Extract a fresh release ZIP."
        }
    }
    foreach ($required in @('Install.ps1','Install.cmd','km003c-backup.exe','km003c-overlay-host.exe','overlays/qr/gate.bin','overlays/qr/extension.bin','overlays/screen/gate.bin','overlays/screen/extension.bin')) {
        if (!$seen.ContainsKey($required)) { throw "Missing release file: $required" }
    }
    Write-Host "Package verified: $($manifest.project_version), FW $($manifest.stock_firmware), HW $($manifest.hardware)"
}

Assert-Package
if ($CheckPackage) { exit 0 }
if (![Environment]::Is64BitOperatingSystem -or ![Environment]::Is64BitProcess) { throw 'Use 64-bit Windows and 64-bit Windows PowerShell.' }
$script:Japanese = (Read-Host 'Language: 1 English / 2 Japanese') -eq '2'
function T([string]$English, [string]$Japanese) { if ($script:Japanese) { $Japanese } else { $English } }
function Call-Tool([string]$Name, [string[]]$ToolArgs) {
    & (Join-Path $packageRoot $Name) @ToolArgs
    if ($LASTEXITCODE -ne 0) { throw "${Name}: stopped (exit $LASTEXITCODE). No automatic retry." }
}
function Ask-Ready([string]$English, [string]$Japanese) {
    $null = Read-Host (T $English $Japanese)
}
function Confirm-Write([string]$Word) {
    Write-Host (T 'Leave BOTH measurement connectors empty. Connect only the side HID port to this PC.' '測定用の両コネクターを空にし、側面HIDポートだけをPCにつないでください。')
    Ask-Ready 'Unplug HID, hold Exit, reconnect to the SAME PC USB port, release Exit at BOOT Loader. Press Enter when ready.' 'HIDを抜き、Exitを押しながら同じPC側USBポートへ再接続。BOOT Loaderが出たら離し、準備できたらEnter。'
    if ((Read-Host (T "Type $Word to write firmware" "書き込むには $Word と入力")) -cne $Word) { throw 'Cancelled; no write requested.' }
}
$script:Work = if ($DataDirectory) { [IO.Path]::GetFullPath($DataDirectory) } else { Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'KM003C-FW-Extensions' }
$null = New-Item -ItemType Directory -Path $script:Work -Force
$statePath = Join-Path $script:Work 'last-session.json'
$script:Stock = ''
$script:Bundle = ''
if (Test-Path -LiteralPath $statePath) {
    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $script:Stock = [string]$state.stock
        $script:Bundle = [string]$state.bundle
    } catch { Write-Host 'Choose your existing backup/bundle again; saved paths could not be read.' }
}
function Save-Session {
    @{stock=$script:Stock; bundle=$script:Bundle} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}
function New-Output([string]$Label) {
    Join-Path $script:Work ($Label + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
}
function Select-Stock {
    Write-Host "Backup: $script:Stock"
    $value = Read-Host (T 'Qualified backup folder (Enter keeps current)' '純正バックアップのフォルダ（Enterで現在の選択を使用）')
    if ($value) { $script:Stock = $value.Trim().Trim('"') }
    if (!$script:Stock -or !(Test-Path -LiteralPath (Join-Path $script:Stock 'manifest.json'))) { throw 'Choose a completed stock backup folder.' }
    $script:Stock = (Resolve-Path -LiteralPath $script:Stock).Path
    Save-Session
}
function Select-Bundle {
    Write-Host "Bundle: $script:Bundle"
    $value = Read-Host (T 'Private bundle folder (Enter keeps current)' '作成済みbundleフォルダ（Enterで現在の選択を使用）')
    if ($value) { $script:Bundle = $value.Trim().Trim('"') }
    if (!$script:Bundle -or !(Test-Path -LiteralPath (Join-Path $script:Bundle 'bundle.json'))) { throw 'Choose the bundle subfolder of a prepared package.' }
    $script:Bundle = (Resolve-Path -LiteralPath $script:Bundle).Path
    Save-Session
}
Write-Host (T 'Experimental: exact KM003C HW 2.3 / stock FW 2.0.7 only. Keep your private backup and recovery files.' '実験版：既知のKM003C HW 2.3／純正FW 2.0.7専用。個体バックアップと復旧ファイルを保管してください。')
Write-Host "Private files: $script:Work"
while ($true) {
    Write-Host ''
    Write-Host (T '1 Inspect (read only) | 2 First stock backup | 3 Verify recovery reads in BOOT Loader' '1 本体確認（読取のみ） | 2 初回の純正バックアップ | 3 BOOT Loaderで復旧用の読取確認')
    Write-Host (T '4 Prepare QR/capture (offline) | 5 Install prepared extension | 6 Restore stock' '4 QR／キャプチャの準備（オフライン） | 5 準備した拡張を導入 | 6 純正へ復元')
    Write-Host (T '7 Verify local bundle (offline) | 0 Exit' '7 ローカルbundleの照合（オフライン） | 0 終了')
    $choice = Read-Host (T 'Choose' '選択')
    if ($choice -eq '0') { break }
    try {
        switch ($choice) {
            '1' { Call-Tool 'km003c-backup.exe' @('inspect') }
            '2' {
                Write-Host (T 'Start from untouched stock in the normal measurement screen. Connect one meter only; leave both measurement ports empty.' '未改変の純正FWを通常の測定画面で起動。本体は1台だけ接続し、測定用の両ポートは空にしてください。')
                Call-Tool 'km003c-backup.exe' @('inspect')
                $serial = Read-Host (T 'Enter the serial just displayed' '表示されたシリアル番号を入力')
                if (!$serial -or $serial -match '^-' ) { throw 'Serial is required.' }
                $out = New-Output 'stock'
                Call-Tool 'km003c-backup.exe' @('stock','--serial',$serial,'--output',$out)
                $script:Stock = $out
                Save-Session
                Write-Host "Backup: $out"
            }
            '3' {
                Select-Stock
                if (Test-Path -LiteralPath (Join-Path $script:Stock 'dfu-recovery-check/verified.json')) {
                    Call-Tool 'km003c-backup.exe' @('verify','--stock',$script:Stock,'--require-dfu')
                } else {
                    Ask-Ready 'Unplug HID, hold Exit while reconnecting to the SAME PC USB port. Release at BOOT Loader, then Enter. Read only; no flash write.' 'HIDを抜き、Exitを押しながら同じPC側USBポートへ再接続。BOOT Loaderで離し、Enter。読取のみで書込みはしません。'
                    Call-Tool 'km003c-backup.exe' @('dfu-check','--stock',$script:Stock)
                }
            }
            '4' {
                Select-Stock
                $variant = switch (Read-Host (T '1 QR / 2 Capture' '1 QR / 2 キャプチャ')) { '1' {'qr'} '2' {'screen'} default { throw 'Choose 1 or 2.' } }
                $out = New-Output "prepared-$variant"
                Call-Tool 'km003c-overlay-host.exe' @('--stock',$script:Stock,'prepare','--variant',$variant,'--overlay',(Join-Path $packageRoot "overlays/$variant"),'--output',$out)
                $script:Bundle = Join-Path $out 'bundle'
                Save-Session
                Write-Host "Bundle: $script:Bundle"
                Write-Host (T 'Copy the backup and this complete prepared folder to another safe location before installing.' '導入前にバックアップと、このpreparedフォルダ全体を別の安全な場所にもコピーしてください。')
            }
            '5' {
                Select-Stock
                Select-Bundle
                Call-Tool 'km003c-overlay-host.exe' @('--stock',$script:Stock,'audit','--bundle',$script:Bundle)
                $previous = (Read-Host (T 'Replacing an extension? Enter its OLD private bundle folder; Enter for untouched stock.' '拡張を入れ替える場合は旧bundleフォルダを入力。未改変の純正からならEnter。')).Trim().Trim('"')
                $toolArgs = @('--stock',$script:Stock,'flash-probe','--bundle',$script:Bundle,'--output',(New-Output 'install'))
                if ($previous) { $toolArgs += @('--previous-bundle',$previous) }
                Confirm-Write 'INSTALL'
                Call-Tool 'km003c-overlay-host.exe' $toolArgs
                Call-Tool 'km003c-overlay-host.exe' @('--stock',$script:Stock,'start-probe','--bundle',$script:Bundle,'--output',(New-Output 'start'))
            }
            '6' {
                Select-Stock
                Select-Bundle
                Call-Tool 'km003c-overlay-host.exe' @('--stock',$script:Stock,'audit','--bundle',$script:Bundle)
                Confirm-Write 'RESTORE'
                Call-Tool 'km003c-overlay-host.exe' @('--stock',$script:Stock,'restore','--bundle',$script:Bundle,'--output',(New-Output 'restore'))
                Call-Tool 'km003c-overlay-host.exe' @('--stock',$script:Stock,'start-stock','--bundle',$script:Bundle,'--output',(New-Output 'stock-start'))
            }
            '7' {
                Select-Stock
                Select-Bundle
                Call-Tool 'km003c-overlay-host.exe' @('--stock',$script:Stock,'audit','--bundle',$script:Bundle)
            }
            default { Write-Host (T 'Choose 0 through 7.' '0〜7を選んでください。') }
        }
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
        Write-Host (T 'Stopped. No automatic retry or recovery. Keep the evidence. If a transfer failed, physically reconnect with Exit held before any further device operation. See docs/INSTALL.md.' '処理を停止しました。自動再試行・自動復旧は行いません。記録を保管し、転送失敗時は次の実機操作の前にExitを押しながら接続し直してください。docs/INSTALL.ja.mdを参照。')
    }
    Ask-Ready 'Press Enter to return to the menu' 'メニューへ戻るにはEnter'
}
