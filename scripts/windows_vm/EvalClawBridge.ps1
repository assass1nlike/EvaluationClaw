param(
    [int]$Port = 7766,
    [string]$ReadyMarker = 'C:\ProgramData\EvalClaw\provisioning-ready'
)

$ErrorActionPreference = 'Stop'
while (-not (Test-Path -LiteralPath $ReadyMarker)) {
    Start-Sleep -Seconds 2
}

$interactiveRoot = 'C:\ProgramData\EvalClaw\interactive-provisioning'
$interactiveRequired = Join-Path $interactiveRoot 'required'
if (Test-Path -LiteralPath $interactiveRequired) {
    $interactiveDeadline = (Get-Date).AddSeconds(180)
    $interactiveReady = Join-Path $interactiveRoot 'ready'
    $interactiveFailed = Join-Path $interactiveRoot 'failed'
    $interactiveSetup = Join-Path $interactiveRoot 'setup.ps1'
    if (-not (Test-Path -LiteralPath $interactiveReady) -and (Test-Path -LiteralPath $interactiveSetup)) {
        $interactiveOutput = & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
            -NoProfile -ExecutionPolicy Bypass -File $interactiveSetup 2>&1
        if ($LASTEXITCODE -ne 0 -and -not (Test-Path -LiteralPath $interactiveFailed)) {
            $interactiveOutput | Out-File -LiteralPath $interactiveFailed -Encoding UTF8
        }
    }
    while (-not (Test-Path -LiteralPath $interactiveReady)) {
        if (Test-Path -LiteralPath $interactiveFailed) {
            throw "EvalClaw interactive provisioning failed: $(Get-Content -LiteralPath $interactiveFailed -Raw)"
        }
        if ((Get-Date) -ge $interactiveDeadline) {
            throw 'Timed out waiting for EvalClaw interactive provisioning.'
        }
        Start-Sleep -Seconds 2
    }
}

$sessions = @{}
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add("http://+:$Port/")
$listener.Start()

function Send-Json {
    param($Context, $Payload, [int]$StatusCode = 200)
    $json = $Payload | ConvertTo-Json -Depth 20 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $Context.Response.StatusCode = $StatusCode
    $Context.Response.ContentType = 'application/json; charset=utf-8'
    $Context.Response.ContentLength64 = $bytes.Length
    $Context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $Context.Response.OutputStream.Close()
}

function Read-Json {
    param($Request)
    if (-not $Request.HasEntityBody) { return @{} }
    $reader = [IO.StreamReader]::new($Request.InputStream, $Request.ContentEncoding)
    try {
        $text = $reader.ReadToEnd()
    } finally {
        $reader.Dispose()
    }
    if (-not $text) { return @{} }
    return $text | ConvertFrom-Json
}

function Limit-Text {
    param([string]$Text, [int]$Limit = 16000)
    if ($null -eq $Text) { return '' }
    if ($Text.Length -le $Limit) { return $Text }
    $half = [math]::Floor($Limit / 2)
    return $Text.Substring(0, $half) + "`n... output clipped ...`n" + $Text.Substring($Text.Length - $half)
}

function Invoke-CommandText {
    param([string]$Command, [int]$TimeoutSeconds = 120)
    if (-not $Command) {
        return @{ exit_code = 1; stdout = ''; stderr = 'command is empty'; timed_out = $false }
    }
    $temp = Join-Path $env:TEMP ("evalclaw-command-{0}.ps1" -f [guid]::NewGuid().ToString('N'))
    $wrapped = @"
`$global:LASTEXITCODE = 0
try {
$Command
} catch {
    [Console]::Error.WriteLine((`$_ | Out-String))
    exit 1
}
exit [int]`$global:LASTEXITCODE
"@
    Set-Content -LiteralPath $temp -Value $wrapped -Encoding UTF8
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$temp`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.CreateNoWindow = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    try {
        [void]$process.Start()
        $process.StandardInput.Close()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $completed = $process.WaitForExit([math]::Max(1, $TimeoutSeconds) * 1000)
        if (-not $completed) {
            $process.Kill()
        }
        $process.WaitForExit()
        return @{
            exit_code = if ($completed) { $process.ExitCode } else { 124 }
            stdout = Limit-Text $stdoutTask.Result
            stderr = Limit-Text $stderrTask.Result
            timed_out = -not $completed
        }
    } finally {
        $process.Dispose()
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Check {
    param($Check)
    $method = [string]$Check.method
    if (-not $method) { $method = 'command' }
    $checkId = if ($null -ne $Check.id) { [string]$Check.id } else { [string]$Check.check_id }
    if ($method -eq 'command') {
        $timeout = if ($null -ne $Check.timeout_s) { [int]$Check.timeout_s } else { 180 }
        $result = Invoke-CommandText -Command ([string]$Check.command) -TimeoutSeconds $timeout
        $expected = if ($null -ne $Check.expected_exit_code) { [int]$Check.expected_exit_code } else { 0 }
        $passed = $result.exit_code -eq $expected
        return @{ id = $checkId; passed = $passed; result = $result }
    }
    if ($method -eq 'file_exists') {
        $passed = Test-Path -LiteralPath ([string]$Check.path)
        return @{ id = $checkId; passed = $passed; path = [string]$Check.path }
    }
    return @{ id = $checkId; passed = $false; error = "unsupported check method: $method" }
}

function Invoke-Checks {
    param($Checks)
    $results = @()
    foreach ($check in @($Checks)) {
        $results += Invoke-Check $check
    }
    return $results
}

function Save-Screenshot {
    $root = 'C:\ProgramData\EvalClaw\screenshots'
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $path = Join-Path $root ("screen-{0}.png" -f [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff'))
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $bounds = [Windows.Forms.SystemInformation]::VirtualScreen
    $bitmap = [Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size)
        $bitmap.Save($path, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    return $path
}

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        try {
            $method = $context.Request.HttpMethod.ToUpperInvariant()
            $path = $context.Request.Url.AbsolutePath.TrimEnd('/')
            if ($method -eq 'GET' -and $path -eq '/health') {
                Send-Json $context @{ status = 'ok'; ready = $true; user = [Environment]::UserName }
                continue
            }
            if ($method -eq 'POST' -and $path -eq '/sessions') {
                $payload = Read-Json $context.Request
                $session = $payload.session
                $checks = @($session.baseline_checks)
                $results = @(Invoke-Checks $checks)
                $verified = @($results | Where-Object { -not $_.passed }).Count -eq 0
                $id = [guid]::NewGuid().ToString('N')
                $sessions[$id] = $session
                Send-Json $context @{
                    session_id = $id
                    baseline_verified = $verified
                    baseline_results = $results
                    observation = if ($verified) { 'Windows session ready; baseline verified.' } else { 'Windows baseline failed.' }
                }
                continue
            }
            if ($path -match '^/sessions/([^/]+)/actions$' -and $method -eq 'POST') {
                $payload = Read-Json $context.Request
                $action = [string]$payload.action
                $args = $payload.args
                if ($action -eq 'run_command') {
                    $timeout = if ($null -ne $args.timeout) { [int]$args.timeout } else { 120 }
                    $result = Invoke-CommandText -Command ([string]$args.command) -TimeoutSeconds $timeout
                    Send-Json $context @{ observation = "exit_code=$($result.exit_code)`nstdout:`n$($result.stdout)`nstderr:`n$($result.stderr)"; command_result = $result; error = if ($result.exit_code -eq 0) { $null } else { "command exited $($result.exit_code)" } }
                } elseif ($action -eq 'read_file') {
                    $content = Get-Content -LiteralPath ([string]$args.path) -Raw
                    Send-Json $context @{ observation = Limit-Text $content; path = [string]$args.path }
                } elseif ($action -eq 'write_file') {
                    $target = [string]$args.path
                    $parent = Split-Path -Parent $target
                    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
                    [IO.File]::WriteAllText($target, [string]$args.content, [Text.UTF8Encoding]::new($false))
                    Send-Json $context @{ observation = "wrote $target"; path = $target }
                } elseif ($action -eq 'list_files') {
                    $target = if ([string]$args.path) { [string]$args.path } else { 'C:\Users\Public' }
                    $items = Get-ChildItem -Force -LiteralPath $target | Select-Object Name, FullName, Length, LastWriteTime
                    Send-Json $context @{ observation = Limit-Text ($items | Format-Table -AutoSize | Out-String); path = $target }
                } elseif ($action -eq 'screenshot') {
                    $screen = Save-Screenshot
                    Send-Json $context @{ observation = "screenshot saved inside guest: $screen"; path = $screen }
                } else {
                    Send-Json $context @{ error = "unsupported bridge action: $action"; observation = "unsupported bridge action: $action" } 400
                }
                continue
            }
            if ($path -match '^/sessions/([^/]+)/evaluate$' -and $method -eq 'POST') {
                $payload = Read-Json $context.Request
                $results = @(Invoke-Checks @($payload.evaluation.checks))
                $total = [math]::Max(1, $results.Count)
                $passed = @($results | Where-Object { $_.passed }).Count
                $score = $passed / $total
                Send-Json $context @{ score = $score; done = $passed -eq $total; checks = $results; observation = "passed_checks=$passed/$total" }
                continue
            }
            if ($path -match '^/sessions/([^/]+)$' -and $method -eq 'DELETE') {
                [void]$sessions.Remove($Matches[1])
                Send-Json $context @{ deleted = $true }
                continue
            }
            Send-Json $context @{ error = 'not found' } 404
        } catch {
            try { Send-Json $context @{ error = $_.Exception.Message; observation = $_.Exception.Message } 500 } catch {}
        }
    }
} finally {
    $listener.Stop()
    $listener.Close()
}
