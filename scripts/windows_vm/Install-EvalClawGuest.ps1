param(
    [Parameter(Mandatory = $true)][string]$BridgeSource,
    [Parameter(Mandatory = $true)][string]$BootstrapSource,
    [int]$Port = 7766
)

$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\EvalClaw'
New-Item -ItemType Directory -Force -Path $root | Out-Null
Copy-Item -LiteralPath $BridgeSource -Destination (Join-Path $root 'EvalClawBridge.ps1') -Force
Copy-Item -LiteralPath $BootstrapSource -Destination (Join-Path $root 'EvalClawSeedBootstrap.ps1') -Force

& netsh.exe http delete urlacl url="http://+:$Port/" | Out-Null
& netsh.exe http add urlacl url="http://+:$Port/" user='BUILTIN\Users' | Out-Null
New-NetFirewallRule -DisplayName 'EvalClaw guest bridge' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -ErrorAction SilentlyContinue | Out-Null

$bootstrapAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\EvalClaw\EvalClawSeedBootstrap.ps1"'
$bootstrapTrigger = New-ScheduledTaskTrigger -AtStartup
$bootstrapPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'EvalClaw Seed Bootstrap' -Action $bootstrapAction -Trigger $bootstrapTrigger -Principal $bootstrapPrincipal -Force | Out-Null

$bridgeCommand = 'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\ProgramData\EvalClaw\EvalClawBridge.ps1"'
New-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'EvalClawBridge' -Value $bridgeCommand -PropertyType String -Force | Out-Null
Remove-Item -LiteralPath (Join-Path $root 'provisioning-ready') -Force -ErrorAction SilentlyContinue
