> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Graphite Environment - Learnings and Notes

## Installation

- **Docker image**: `graphiteapp/graphite-statsd:latest` is the official all-in-one image (graphite-web + carbon + whisper + statsd)
- **Ports**: 80 (web UI), 2003 (Carbon plaintext), 2004 (Carbon pickle), 2023 (Carbon aggregator), 2024 (Carbon aggregator pickle), 8125/udp (statsd), 8126 (statsd admin)
- **collectd**: Installed via apt-get on the host VM, sends real metrics to Carbon via `write_graphite` plugin

## Real Data Sources

### NAB (Numenta Anomaly Benchmark) Dataset
- GitHub: `https://raw.githubusercontent.com/numenta/NAB/master/data/`
- Contains REAL server metrics from actual production systems
- CSV format: `timestamp,value` with timestamps like `2014-04-01 00:00:00`
- Timestamps are shifted to current time (ending 2 minutes before now) to fit within Graphite retention window
- Original metric values are preserved unchanged
- 11 files, ~59,974 data points total, ~1.7 MB

### collectd Real VM Metrics
- Collects from the running QEMU VM itself
- CPU, memory, disk, network, load, swap, processes, entropy, uptime, df
- Config at `/etc/collectd/collectd.conf` with `write_graphite` output plugin
- Sends to `localhost:2003` with `collectd.` prefix

## Service Timing

- Docker daemon: ~30s to start, polled with `docker info`
- Graphite container: ~60s for web UI (HTTP 200), polled with `curl -s -o /dev/null -w "%{http_code}"`
- Carbon receiver: ~30s for port 2003 ready, polled with `nc -z localhost 2003`
- Metric index rebuild: `docker exec graphite /opt/graphite/bin/build-index.sh` needed after bulk data feed
- Total post_start time: ~2 minutes

## Graphite Web UI Pages

| URL | Page | Description |
|-----|------|-------------|
| `/` | Graphite Browser | Tree panel + Composer window |
| `/composer` | Composer | Standalone graph composer |
| `/dashboard` | Dashboard | Dashboard creator/viewer |
| `/render?target=...&format=json` | Render API | Programmatic data access |
| `/metrics/index.json` | Metric Index | List all metrics |
| `/metrics/find?query=pattern` | Metric Find | Search metrics |

## Firefox Configuration

- Snap-installed Firefox requires warm-up launch with `--headless` to create profile
- `user.js` must disable: aboutwelcome, checkDefaultBrowser, telemetry, pocket, fxaccounts
- Homepage set to `http://localhost/` via `browser.startup.homepage`
- Use `setsid` when launching Firefox from hooks to prevent SIGHUP on SSH disconnect

## Known Quirks

1. **collectd data delay**: collectd metrics may take 30-60s to appear after starting
2. **NAB data null points**: The 24h view may show null datapoints at boundaries since NAB data is time-shifted
3. **Snap mount warnings**: Firefox snap produces `update.go:85: cannot change mount namespace` warnings - harmless
4. **Metric index**: After bulk data feed, must rebuild index with `build-index.sh` or metrics won't appear in tree immediately
5. **Docker Hub rate limits**: May need DockerHub authentication for `docker pull` on shared infrastructure
