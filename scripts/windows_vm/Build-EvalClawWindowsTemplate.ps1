param(
    [Parameter(Mandatory = $true)][string]$IsoPath,
    [string]$VmName = 'windows-11-evalclaw-base-2025',
    [string]$BaseFolder = 'D:\localwork\vm_backends\windows',
    [string]$GuestUser = 'EvalAdmin',
    [string]$GuestPassword = 'EvalClawLocal!2026',
    [int]$MemoryMB = 4096,
    [int]$CpuCount = 4,
    [int]$DiskMB = 81920
)

$ErrorActionPreference = 'Stop'
$vbox = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$iso = (Resolve-Path -LiteralPath $IsoPath).Path
$vmRoot = Join-Path $BaseFolder $VmName
$disk = Join-Path $vmRoot "$VmName.vdi"

if (-not (Test-Path -LiteralPath $vbox -PathType Leaf)) {
    throw "VBoxManage not found: $vbox"
}
if (& $vbox list vms | Select-String -SimpleMatch ('"' + $VmName + '"')) {
    throw "VirtualBox VM already exists; refusing to overwrite it: $VmName"
}

function Invoke-VBox {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    [string[]]$display = $Arguments.Clone()
    for ($index = 0; $index -lt $display.Count - 1; $index++) {
        if ($display[$index] -in @('--password', '--user-password', '--admin-password')) {
            $display[$index + 1] = '<redacted>'
        }
    }
    Write-Host ('VBoxManage ' + ($display -join ' '))
    & $vbox @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "VBoxManage failed with exit code $LASTEXITCODE."
    }
}

New-Item -ItemType Directory -Force -Path $BaseFolder | Out-Null
Invoke-VBox createvm --name $VmName --ostype Windows11_64 --basefolder $BaseFolder --register
Invoke-VBox modifyvm $VmName --memory $MemoryMB --cpus $CpuCount --vram 128 `
    --graphicscontroller vboxsvga --firmware efi --tpm-type 2.0 --ioapic on `
    --boot1 dvd --boot2 disk --boot3 none --boot4 none --nic1 nat --audio-enabled off
Invoke-VBox createmedium disk --filename $disk --size $DiskMB --format VDI
Invoke-VBox storagectl $VmName --name 'SATA Controller' --add sata --controller IntelAhci
Invoke-VBox storageattach $VmName --storagectl 'SATA Controller' --port 0 --device 0 `
    --type hdd --medium $disk

$postInstallCommand = 'reg.exe add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f'
Invoke-VBox unattended install $VmName --iso $iso --user $GuestUser `
    --user-password $GuestPassword --admin-password $GuestPassword `
    --full-user-name 'EvalClaw Administrator' --locale en_US --country US `
    --language en-US --hostname evalclaw-base.local --image-index 1 `
    --install-additions --post-install-command $postInstallCommand --start-vm headless

$deadline = (Get-Date).AddMinutes(90)
$guestReady = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 20
    $state = (& $vbox showvminfo $VmName --machinereadable | Select-String '^VMState=').Line
    Write-Host "Waiting for Windows and Guest Additions: $state"
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $vbox guestcontrol $VmName run --username $GuestUser --password $GuestPassword `
            --exe 'C:\Windows\System32\cmd.exe' --wait-stdout --wait-stderr `
            --timeout 15000 -- cmd.exe /c ver *> $null
        $guestControlExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($guestControlExitCode -eq 0) {
        $guestReady = $true
        break
    }
}
if (-not $guestReady) {
    throw 'Windows unattended installation did not expose Guest Additions within 90 minutes.'
}

$guestTemp = 'C:\Windows\Temp\EvalClawGuestSetup'
Invoke-VBox guestcontrol $VmName mkdir --parents --username $GuestUser `
    --password $GuestPassword $guestTemp
$sources = @(
    (Join-Path $scriptRoot 'EvalClawBridge.ps1'),
    (Join-Path $scriptRoot 'EvalClawSeedBootstrap.ps1'),
    (Join-Path $scriptRoot 'Install-EvalClawGuest.ps1')
)
foreach ($source in $sources) {
    $guestTarget = Join-Path $guestTemp (Split-Path -Leaf $source)
    Invoke-VBox guestcontrol $VmName copyto --username $GuestUser --password $GuestPassword `
        $source $guestTarget
}
Invoke-VBox guestcontrol $VmName run --username $GuestUser --password $GuestPassword `
    --exe 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
    --wait-stdout --wait-stderr --timeout 180000 -- powershell.exe -NoProfile `
    -ExecutionPolicy Bypass -File "$guestTemp\Install-EvalClawGuest.ps1" `
    -BridgeSource "$guestTemp\EvalClawBridge.ps1" `
    -BootstrapSource "$guestTemp\EvalClawSeedBootstrap.ps1"

& $vbox guestcontrol $VmName run --username $GuestUser --password $GuestPassword `
    --exe 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
    --timeout 30000 -- powershell.exe -NoProfile -Command `
    "Remove-Item 'C:\ProgramData\EvalClaw\provisioning-ready' -Force -ErrorAction SilentlyContinue; shutdown.exe /s /t 0 /f" 2>$null

$deadline = (Get-Date).AddMinutes(10)
do {
    Start-Sleep -Seconds 5
    $state = (& $vbox showvminfo $VmName --machinereadable | Select-String '^VMState=').Line
} while ($state -notmatch 'poweroff' -and (Get-Date) -lt $deadline)
if ($state -notmatch 'poweroff') {
    throw "Windows template did not power off cleanly: $state"
}

Invoke-VBox snapshot $VmName take evalclaw-ready --description 'EvalClaw Windows evaluation base with guest bridge and NoCloud bootstrap'
Write-Host "Windows EvalClaw template is ready: $VmName"
