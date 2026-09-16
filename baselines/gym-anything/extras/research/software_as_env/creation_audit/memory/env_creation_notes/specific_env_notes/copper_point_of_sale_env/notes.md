> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Copper Point of Sale Environment - Lessons Learned

## Application Details

- **App**: NCH Copper Point of Sale v3.06 (July 2018, no longer updated)
- **Developer**: NCH Software (Australian company)
- **Installer**: Web stub `possetupfree.exe` (~554KB), downloads full app during install
- **Install path**: `C:\Program Files (x86)\NCH Software\Copper\copper.exe`
- **Process name**: `copper` (or `copper.exe`)
- **License**: Unlicensed Non-enterprise (free for non-commercial use, no restrictions)

## Critical Discovery: NCH Installers Have NO Silent Install Flags

NCH Software uses a custom installer framework that does **not** support any silent install flags. Unlike InnoSetup (`/VERYSILENT`), MSI (`/qn`), or NSIS (`/S`), NCH installers require GUI interaction.

### What Was Tried and Failed

1. **`possetup.exe -LQUIET`** - Documented online for some NCH products, but does NOT work for Copper
2. **`possetup.exe /S`** - NSIS flag, not applicable
3. **`possetup.exe /silent`** - No effect
4. **Win32 API clicks from SSH Session 0** - `SetCursorPos + mouse_event` runs in Session 0 which has no GUI access
5. **VNC clicks via vncdotool** - Correct syntax (`vncdotool move X Y click 1`) but clicks don't register on Copper's windows

### What Works: PyAutoGUI TCP Server

The gym_anything framework auto-starts a PyAutoGUI TCP server on port 5555 in the GUI session. This is the **only reliable method** for automating Copper POS UI from SSH scripts.

```powershell
# PowerShell helper to send PyAutoGUI commands
function Send-PyAutoGUI {
    param([hashtable]$Command, [int]$Port = 5555)
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect("127.0.0.1", $Port)
    $json = ($Command | ConvertTo-Json -Compress) + "`n"
    $stream = $client.GetStream()
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    $writer.WriteLine($json.TrimEnd())
    $reader = New-Object System.IO.StreamReader($stream)
    $resp = $reader.ReadLine()
    $client.Close()
    return $resp
}

# Click at coordinates
Send-PyAutoGUI @{action="click"; x=788; y=539}

# Press key
Send-PyAutoGUI @{action="press"; keys="escape"}
```

## Installation Flow (GUI via PyAutoGUI)

1. **Stage installer**: Download `possetupfree.exe` in pre_start, save to `C:\Windows\Temp\possetup.exe`
2. **Launch via schtasks /IT**: Run installer in interactive GUI session
3. **Wait 20s**: Installer takes time to load and download components
4. **Escape** to dismiss any OneDrive or notification popups (safe if not present)
5. **Click title bar (640, 150)**: Ensure installer window has focus
6. **Click Next (788, 539)**: Accept EULA
7. **Retry Next click**: Sometimes first click doesn't register
8. **Wait up to 120s**: Web stub downloads full app, installs, auto-launches Copper
9. **Dismiss Quick Start Wizard**: Cancel at (851, 512)
10. **Click OK on "Wizard Cancelled"**: OK at (791, 455)

## OneDrive Interference

OneDrive popups can steal focus from the installer. The initial approach of clicking "No thanks" at (1166, 627) backfired when the popup wasn't present (the click hit something else).

**Solution**: Use `Escape` key instead of coordinate-based click. Escape is safe whether or not a popup is present, and it closes any NCH notification dialogs too.

Additionally, OneDrive is fully disabled in post_start:
- Kill OneDrive/OneDriveSetup processes
- Remove from startup registry
- Disable via Group Policy
- Uninstall with 30s timeout (use `WaitForExit(30000)`, NOT `-Wait`)

## Warm-up Launch Pattern

After installation, Copper auto-launches with the Quick Start Wizard. After dismissing it:
1. Kill Copper (`Stop-Process -Name copper`)
2. Do a second warm-up launch via schtasks
3. Run dialog dismissal script
4. Kill again

This ensures subsequent launches (during pre_task hooks) have no first-run dialogs.

## UI Coordinates (1280x720)

| Element | Coordinates |
|---------|-------------|
| Installer title bar | (640, 150) |
| EULA Next button | (788, 539) |
| Quick Start Cancel | (851, 512) |
| "Wizard Cancelled" OK | (791, 455) |
| Neutral/safe click area | (640, 350) |

## Menu Structure

- **Copper**: Log On, Register Software, Exit
- **Reports**: Sales reports
- **View**: Transactions, Refunds, Drafts, Items (Ctrl+T), Salespeople (Ctrl+F), Customers (Ctrl+C), Security Log, Dual Screen, Explorer Bar
- **Restaurant**: Restaurant-mode features
- **Tools**: Back Up Data, Restore Data, Refunds, Options
- **Help**: Help topics

## Data

- **Products**: 100 items in CSV with columns: Item Name, Description, Category, Price, Cost, Quantity, Barcode, SKU, Tax Rate, Taxable
- **Customers**: 30 records in CSV with columns: First Name, Last Name, Email, Phone, Address, City, State, Zip Code, Country, Company, Notes
- **Location**: `C:\Users\Docker\Documents\CopperData\`
- **Sources**: Shopify Partners product-csvs, GitHub grocery dataset, datablist sample customers

## Tasks

| Task | Difficulty | Description |
|------|-----------|-------------|
| add_inventory_item | easy | Add "Organic Green Tea 20pk" to inventory |
| process_sale | easy | Ring up 3 items and complete cash payment |
| generate_sales_report | medium | Generate monthly sales report |
| add_customer | easy | Add customer "Maria Rodriguez" |
| configure_receipt | medium | Configure receipt for "Green Valley Market" |

## Timing

- **env.reset() fresh**: ~240s total (pre_start: ~2s, post_start: ~108s, checkpoint: ~40s, pre_task: ~42s)
- **env.reset() from cache**: ~130s (checkpoint restore: ~87s, pre_task: ~42s)
- **Pre-task setup**: ~42s (launch via schtasks, wait 20s, dismiss dialogs)
