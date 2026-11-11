param(
    [ValidateSet('qr', 'screen')][string]$Variant = 'qr',
    [ValidateSet('2.0.7')][string]$StockFirmware = '2.0.7',
    [string]$Python = 'python',
    [string]$Clang = 'clang'
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & $Python tools/build_firmware.py --stock-fw $StockFirmware --variant $Variant --clang $Clang
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
} finally { Pop-Location }
