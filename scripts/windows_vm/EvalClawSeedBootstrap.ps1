param(
    [string]$StateRoot = 'C:\ProgramData\EvalClaw\seed-state',
    [string]$ReadyMarker = 'C:\ProgramData\EvalClaw\provisioning-ready',
    [string]$RestartMarker = 'C:\ProgramData\EvalClaw\restart-after-provisioning',
    [int]$WaitSeconds = 180
)

$ErrorActionPreference = 'Stop'
$restartProperty = '/EvalClaw/RestartAfterProvisioning'
$vboxControl = Join-Path $env:SystemRoot 'System32\VBoxControl.exe'
if (Test-Path -LiteralPath $vboxControl) {
    & $vboxControl guestproperty delete $restartProperty 2>$null | Out-Null
}
New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
& icacls.exe $StateRoot /inheritance:r `
    /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to protect EvalClaw seed state.'
}
Remove-Item -LiteralPath $ReadyMarker -Force -ErrorAction SilentlyContinue

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$userData = $null
while ((Get-Date) -lt $deadline) {
    foreach ($drive in Get-PSDrive -PSProvider FileSystem) {
        $candidate = Join-Path $drive.Root 'user-data'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $userData = $candidate
            break
        }
    }
    if ($userData) { break }
    Start-Sleep -Seconds 2
}

if (-not $userData) {
    New-Item -ItemType File -Force -Path $ReadyMarker | Out-Null
    exit 0
}

$hash = (Get-FileHash -LiteralPath $userData -Algorithm SHA256).Hash.ToLowerInvariant()
$doneMarker = Join-Path $StateRoot "$hash.done"
if (Test-Path -LiteralPath $doneMarker) {
    New-Item -ItemType File -Force -Path $ReadyMarker | Out-Null
    exit 0
}

$content = Get-Content -LiteralPath $userData -Raw
if ($content -notmatch '^\s*#ps1(?:_sysnative)?') {
    throw "Unsupported config-drive user-data format; expected PowerShell NoCloud user-data."
}

$scriptPath = Join-Path $StateRoot "$hash.ps1"
$logPath = Join-Path $StateRoot "$hash.log"
$failedMarker = Join-Path $StateRoot "$hash.failed"
Set-Content -LiteralPath $scriptPath -Value $content -Encoding UTF8
Remove-Item -LiteralPath $failedMarker -Force -ErrorAction SilentlyContinue
try {
    $output = & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -NoProfile -ExecutionPolicy Bypass -File $scriptPath 2>&1
    $exitCode = $LASTEXITCODE
    $output | Out-File -LiteralPath $logPath -Encoding UTF8
    if ($exitCode -ne 0) {
        throw "EvalClaw config-drive provisioning failed with exit code $exitCode."
    }
} catch {
    $_ | Out-String | Add-Content -LiteralPath $logPath -Encoding UTF8
    Set-Content -LiteralPath $failedMarker -Value $_.Exception.Message -Encoding UTF8
    throw
}

New-Item -ItemType File -Force -Path $doneMarker | Out-Null
if (Test-Path -LiteralPath $RestartMarker) {
    Remove-Item -LiteralPath $RestartMarker -Force
    if (Test-Path -LiteralPath $vboxControl) {
        & $vboxControl guestproperty set $restartProperty pending 2>$null | Out-Null
    }
    & shutdown.exe /r /t 0 /f
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to restart Windows after EvalClaw provisioning.'
    }
    exit 0
}
New-Item -ItemType File -Force -Path $ReadyMarker | Out-Null
