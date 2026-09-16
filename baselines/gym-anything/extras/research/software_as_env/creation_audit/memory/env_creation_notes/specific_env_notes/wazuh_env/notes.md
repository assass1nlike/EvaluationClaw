> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Wazuh SIEM Environment Notes

## Architecture
- Docker-in-QEMU: 3-container stack using official `wazuh/wazuh-docker` compose file
- **wazuh-wazuh.manager-1**: Wazuh manager + API (ports 1514, 1515, 55000)
- **wazuh-wazuh.indexer-1**: OpenSearch (port 9200)
- **wazuh-wazuh.dashboard-1**: Wazuh dashboard (port 443 → 5601)
- Dashboard accessible at `https://localhost` (HTTPS, self-signed cert)
- Wazuh version: 4.9.2

## Credentials
- Dashboard: `admin` / `SecretPassword`
- Wazuh API: `wazuh-wui` / `MyS3cr37P450r.*-`
- OpenSearch: `admin` / `SecretPassword`
- SSH: `ga` / `password123`

## CRITICAL: Docker Compose v2 Container Naming
- **Docker Compose v2** names containers `<project_dir>-<service_name>-<replica>`
- Project dir = `wazuh` (deploy dir), service = `wazuh.manager` → container: `wazuh-wazuh.manager-1`
- **NEVER** use `docker exec wazuh-manager` — that container does NOT exist
- Always use: `docker exec wazuh-wazuh.manager-1 ...`
- Set `WAZUH_MANAGER_CONTAINER="wazuh-wazuh.manager-1"` in task_utils.sh

## CRITICAL: Wazuh 4.9.x Navigation URLs
The URL structure changed in Wazuh 4.9.x. These are correct working URLs:
```
Home:         https://localhost/app/wz-home
Groups:       https://localhost/app/endpoint-groups#/manager/?tab=groups
Rules:        https://localhost/app/rules#/manager/tab=ruleset
Configuration: https://localhost/app/settings#/manager/?tab=configuration
Agents:       https://localhost/app/endpoints-summary
SCA:          https://localhost/app/configuration-assessment#/overview/?tab=sca&agentId=000
```
**Wrong** (show "Application Not Found"): `app/wazuh#/manager/groups`, `app/wazuh#/manager/ruleset`

## CRITICAL: SSL Certificate Warning
- Firefox shows "Warning: Potential Security Risk Ahead" on every new launch
- Must click: Advanced → "Accept the Risk and Continue"
- Coordinates in 1920x1080: Advanced=(1318, 768), Accept Risk=(1251, 1005)
- `dismiss_ssl_warning()` in task_utils.sh handles this automatically
- Called by both `ensure_firefox_wazuh()` (on first launch) and `navigate_firefox_to()` (on each nav)

## Wazuh API Authentication
```bash
TOKEN=$(curl -sk -u "wazuh-wui:MyS3cr37P450r.*-" \
    -X POST "https://localhost:55000/security/user/authenticate?raw=true")
curl -sk -X GET "https://localhost:55000/groups" \
    -H "Authorization: Bearer ${TOKEN}"
```

## Real Data in the Environment
- **Alerts**: 187 real Wazuh alerts in `wazuh-alerts-*` OpenSearch indices
  - Medium (level 7-11): 46, Low (level 0-6): 141
- **SCA**: CIS Benchmark for Amazon Linux 2023, agent 000 (wazuh-manager itself)
  - Score: 52%, 51 passed, 46 failed, 87 invalid
- **Agent groups pre-created**: database-servers, default, linux-servers, web-servers, windows-workstations
  - `dmz-servers` group is NOT created (start state for add_agent_group task)

## Agent 000 (Manager)
- Agent 000 = the Wazuh manager container itself
- Shows up in SCA (Configuration Assessment) but NOT in the main endpoints-summary page
- SCA page URL: `app/configuration-assessment#/overview/?tab=sca&agentId=000`

## SCA Dashboard vs Checks Tab
- **Dashboard tab**: Shows compliance score (52%), pass/fail counts, compliance frameworks
- **Checks tab**: Shows individual security check results with title, result, description, rationale, remediation
- Filter dropdown on Checks tab: can filter by result (passed/failed/not applicable)
- Clicking a check row expands it inline showing rationale + remediation text

## Tasks (5 total)
| Task | Start URL | Key Action |
|------|-----------|------------|
| add_agent_group | endpoint-groups#groups | Click "Add new group" → name "dmz-servers" |
| create_custom_rule | rules#ruleset → Custom rules | Add rule 100010 (level 9, if_sid 5710) via XML editor |
| configure_email_alerts | settings#configuration | Edit ossec.conf to enable email_notification |
| manage_sca_policy | configuration-assessment SCA | Checks tab → filter failed → view Remediation |
| check_agent_status | configuration-assessment SCA | Checks tab → click failed check → view detail |

## Task State Resets
- **add_agent_group**: Wazuh API deletes `dmz-servers` group if it exists
- **create_custom_rule**: `docker cp` restores local_rules.xml to version with 100001/100002/100003 but NOT 100010; then `wazuh-control restart`
- **configure_email_alerts**: `docker exec` resets `<email_notification>no</email_notification>` in ossec.conf; then restart
- **manage_sca_policy / check_agent_status**: No state reset needed (read-only SCA viewing tasks)

## OpenSearch Memory Fix
In docker-compose.yml, the indexer needs `MaxDirectMemorySize` set to prevent OOM:
```yaml
- "OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g -XX:MaxDirectMemorySize=1g"
```

## setup_wazuh.sh Structure
1. Install Docker Compose v2 if needed
2. Create deploy dir, copy compose files + certs
3. Pull images and `docker compose up -d`
4. Wait for indexer (up to 5min), manager (2min), dashboard (3min)
5. Set admin password via internal users tool
6. Create agent groups (database-servers, linux-servers, web-servers, windows-workstations)
7. Install Firefox + xdotool + wmctrl
8. Configure X11/VNC
9. Warm-up Firefox launch at https://localhost → dismiss SSL warning
10. Inject security log data into manager container for realistic alerts

## Verifier Notes
- API-based verification where possible (no GUI screenshot comparison)
- `add_agent_group`: `GET /groups?search=dmz-servers` → check group name in response
- `create_custom_rule`: `GET /rules?rule_ids=100010` → check `id: 100010` in response
- `configure_email_alerts`: `docker exec` + grep `<email_notification>yes` in ossec.conf
- `manage_sca_policy`: Screenshot-based (checking filter state in UI)
- `check_agent_status`: Screenshot-based (checking expanded check detail visible)

## Lessons Learned
1. **Container name is critical** — docker compose v2 uses dots in service names: `wazuh.manager` → `wazuh-wazuh.manager-1`
2. **SSL must be dismissed BEFORE login** — every fresh Firefox launch shows the warning
3. **Wazuh URLs changed in 4.9.x** — test actual navigation by clicking through sidebar menu, don't guess from documentation
4. **Agent 000 is special** — it's the manager itself, not visible in endpoints-summary, only in SCA
5. **SCA data is inherently real** — Wazuh manager runs CIS Benchmark on itself automatically, giving authentic compliance data
6. **Task differentiation**: manage_sca_policy (filter to failed + view remediation) vs check_agent_status (open Checks tab + expand any check detail) — make sure task descriptions make the completion criteria unambiguous
7. **Real alerts**: The log data injection step (Step 21 in setup_wazuh.sh) is important — without it, only 187 baseline Wazuh system alerts exist
