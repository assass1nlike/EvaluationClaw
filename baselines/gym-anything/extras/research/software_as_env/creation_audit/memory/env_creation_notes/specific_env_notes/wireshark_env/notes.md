> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Wireshark Environment Notes

## Installation Quirks

### Debconf Pre-seeding Required
Wireshark's `wireshark-common` package asks an interactive question about non-root capture permissions. Must pre-seed with:
```bash
echo "wireshark-common wireshark-common/install-setuid boolean true" | debconf-set-selections
```

### PCAP Download URLs
The Wireshark wiki moved to a new URL structure. Old `__moin_import__` URLs no longer work for some files:
- **Working**: `https://wiki.wireshark.org/uploads/27707187aeb30df68e70c8fb9d614981/http.cap`
- **Broken**: `https://wiki.wireshark.org/uploads/__moin_import__/attachments/SampleCaptures/http.cap`
- **Alternative**: GitLab mirror: `https://gitlab.com/wireshark/wireshark/-/wikis/uploads/...`

DNS, SMTP, and telnet samples still work with `__moin_import__` URLs. The install script includes fallback URLs to handle both formats.

### Directory Permissions
When creating directories with `mkdir -p` and then `chmod -R 644`, the directory loses its execute bit, making it untraversable. Always use:
```bash
find /path -type d -exec chmod 755 {} \;
find /path -type f -exec chmod 644 {} \;
```
Instead of `chmod -R 644`.

## Service Timing
- No services needed (Wireshark is a standalone desktop app)
- Wireshark takes 3-5 seconds to fully launch and load a PCAP file
- tshark is available immediately for verification

## Wireshark Version (Ubuntu 22.04)
- Wireshark 3.6.2 (from Ubuntu repos)
- Some newer preferences like `gui.qt.show_welcome_page` don't exist in this version
- Supported preferences: `gui.update.enabled`, `gui.ask_unsaved`

## Verification Strategy
- **Primary**: tshark CLI for programmatic verification (runs inside VM)
- **Pattern**: setup_task.sh records ground truth via tshark, export_result.sh collects results
- **tshark key commands**:
  - Packet count: `tshark -r file.pcap | wc -l`
  - Filtered count: `tshark -r file.pcap -Y "http" | wc -l`
  - Field extraction: `tshark -r file.pcap -T fields -e ip.src -e frame.len`
  - Protocol hierarchy: `tshark -r file.pcap -q -z io,phs`
  - TCP stream: `tshark -r file.pcap -q -z "follow,tcp,ascii,0"`
  - Conversations: `tshark -r file.pcap -q -z conv,tcp`

## /tmp File Ownership
Hooks run as root. Files written to `/tmp/` by one task's setup_task.sh will be owned by root. Each setup_task.sh must clean up `/tmp/initial_*`, `/tmp/ground_truth_*`, etc. at the start to avoid permission issues.

## Data Files
All PCAP files are real network captures from the official Wireshark SampleCaptures wiki page. No synthetic data.

| File | Source | Protocols |
|------|--------|-----------|
| http.cap | Wireshark wiki | HTTP, TCP, DNS |
| dns.cap | Wireshark wiki | DNS (TXT, MX, LOC, PTR, A, AAAA queries) |
| smtp.pcap | Wireshark wiki | SMTP email conversation |
| 200722_tcp_anon.pcapng | Wireshark wiki | Mixed TCP traffic |
| telnet-cooked.pcap | Wireshark wiki | Telnet session (cleartext) |

## Interactive Testing Learnings

### xdotool Race Condition (Critical)
Individual `paramiko.exec_command()` calls for xdotool do NOT work reliably. Each `exec_command()` creates a separate SSH channel, and the X server doesn't process synthetic events consistently across channels.

**Fix**: Bundle ALL xdotool commands into a single bash script and execute via one `exec_command()` call:
```python
def run_script(script, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(
        'cat > /tmp/run.sh << \'SCRIPTEOF\'\n' + script + '\nSCRIPTEOF\n'
        'chmod +x /tmp/run.sh && bash /tmp/run.sh',
        timeout=timeout
    )
    return stdout.read().decode(), stderr.read().decode()
```

### CUA Coordinate Scaling
ask_cua.py returns coordinates normalized to 1280x720. For a 1920x1080 VM, scale:
```python
actual_x = int(cua_x * 1920 / 1280)
actual_y = int(cua_y * 1080 / 720)
```

### Wireshark Filter Bar Click Coordinates
Calculate from window geometry rather than using absolute coordinates:
```bash
eval $(xdotool getactivewindow getwindowgeometry --shell)
FILTER_Y=$((Y + 62))
FILTER_X=$((X + WIDTH / 2))
xdotool mousemove $FILTER_X $FILTER_Y click 1
```

### Wireshark Export Specified Packets Behavior
When using File > Export Specified Packets with the "Displayed" radio button, Wireshark exports the full TCP conversation including ACK segments, not just the HTTP-layer display-filtered packets. For `http.cap` with display filter "http":
- Display shows 4 HTTP packets
- Export creates PCAP with 18 packets (4 HTTP + 14 TCP ACK/SYN/FIN segments)

The verifier was updated to accept this behavior: if all non-HTTP packets are TCP segments, the filter is considered correctly applied.

### Ground Truth Values
| Task | Ground Truth |
|------|-------------|
| filter_http_traffic | 4 HTTP packets in http.cap (43 total) |
| count_dns_queries | 19 DNS queries in dns.cap (38 total = 19 queries + 19 responses) |
| identify_top_talkers | 192.168.200.135 is top sender by IP-layer bytes (10,309 bytes via ip.len) |
| follow_tcp_stream | SMTP stream in smtp.pcap contains EHLO, MAIL FROM, RCPT TO, DATA |
| export_protocol_hierarchy | http.cap contains Ethernet > IP > TCP > HTTP hierarchy |

## Audit Fixes

### PCAP Download Reliability
- Install script now uses `download_pcap()` helper that tries 3 URLs per file
- All 5 PCAPs have wiki.wireshark.org + gitlab.com fallback URLs
- Verification checks for 0-byte files (not just existence)
- All setup_task.sh scripts use `[ ! -s "$FILE" ]` instead of `[ ! -f "$FILE" ]`

### Ground Truth Methodology
- identify_top_talkers now uses `ip.len` (IP-layer bytes) instead of `frame.len` (link-layer)
- This matches what the Wireshark GUI Endpoints dialog shows as "Tx Bytes"

### JSON Safety
- All export_result.sh scripts use `python3 -c` with `json.dump` instead of bash heredocs
- Prevents JSON corruption from special characters in user output

### Task Description Improvements
- Tasks 1 and 2 no longer provide exact filter strings (agents must determine the correct filter)
- Task 4 says "an SMTP packet" instead of "any packet" to avoid stream ambiguity
