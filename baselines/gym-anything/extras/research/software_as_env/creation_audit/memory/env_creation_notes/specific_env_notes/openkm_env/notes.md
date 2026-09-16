> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenKM Environment Notes

## Application Details
- **App**: OpenKM Community Edition 6.3.x
- **Type**: Web-based Document Management System (DMS)
- **Stack**: Java/Tomcat in Docker, H2 embedded database
- **Docker Image**: `openkm/openkm-ce:latest`
- **Port**: 8080
- **Credentials**: `okmAdmin` / `admin`

## Installation Quirks

### Docker Installation
- Install `docker.io` separately from `docker-compose-plugin` — the plugin package does not exist in the base Ubuntu repos of the QEMU VM
- Use fallback chain: `docker-compose-plugin` -> `docker-compose-v2` -> `docker-compose` -> skip
- Docker compose is NOT needed for OpenKM (simple `docker run` is sufficient)

### OpenKM Startup Timing
- OpenKM takes 60-90 seconds to fully initialize (Tomcat + Java startup)
- First-time initialization creates the H2 database and repository structure
- The text extractor runs asynchronously after document uploads — wait a few seconds before relying on full-text search

## REST API Notes

### URL Pattern
- Login page: `/OpenKM/login.jsp` (NOT `/OpenKM/login` which returns 404)
- Frontend: `/OpenKM/frontend/index.jsp`
- REST API base: `/OpenKM/services/rest`
- Swagger: `/OpenKM/services/rest/swagger.json`

### Folder Creation
```bash
# Content-Type MUST be application/json with raw path as body
curl -u okmAdmin:admin -H "Accept: application/json" \
  -X POST -H "Content-Type: application/json" \
  -d "/okm:root/FolderName" \
  "http://localhost:8080/OpenKM/services/rest/folder/createSimple"
```
- Using `application/x-www-form-urlencoded` returns HTTP 415
- Returns HTTP 200 with folder JSON on success

### Document Upload
```bash
curl -u okmAdmin:admin -H "Accept: application/json" \
  -X POST -F "docPath=/okm:root/Folder/file.pdf" -F "content=@/path/to/file.pdf" \
  "http://localhost:8080/OpenKM/services/rest/document/createSimple"
```
- Returns HTTP 200 with document JSON on success
- Returns HTTP 500 if parent folder doesn't exist (create folders first!)

### Keywords (Tags)
```bash
# POST with query parameters (NOT PUT, NOT form body)
curl -u okmAdmin:admin -X POST \
  "http://localhost:8080/OpenKM/services/rest/property/addKeyword?nodeId=/okm:root/path/doc.pdf&keyword=mytag"
```
- Returns HTTP 204 on success
- The parameter is `nodeId` (not `docId`)
- Method is POST (not PUT — returns 405)

## Firefox Integration

### Login Form
- The login page has `onload="document.forms[0].elements[0].focus()"` which auto-focuses the username field
- Login approach: reload page -> type username -> Tab -> type password -> Enter
- DO NOT use JavaScript URLs (`javascript:...`) — Firefox blocks them from the address bar

### Save Password Dialog
- Add `user_pref("signon.rememberSignons", false);` to user.js to suppress
- Also add `signon.autofillForms` and `signon.generation.enabled` = false

### Session Restore
- When killing Firefox with pkill, always clean up lock files and session store:
  ```bash
  find /home/ga -name ".parentlock" -delete
  find /home/ga -name "parent.lock" -delete
  find /home/ga -path "*/sessionstore*" -delete
  ```

### Launching Firefox
- Use `setsid` to properly detach: `DISPLAY=:1 setsid firefox URL &>/dev/null &`
- The snap Firefox profile is at: `find /home/ga/snap/firefox -name "prefs.js"`
- Firefox's first-run tab ("Firefox Privacy Notice") still appears — could add `browser.startup.homepage_override.mstone` to suppress

## Data Management

### Document Repository Structure
```
/okm:root/
├── Compliance/
├── Finance/
├── HR/          (WHO_Constitution.pdf, Art_of_War_Sun_Tzu.txt)
├── Legal/       (Creative_Commons_BY_4.0_Legal_Code.txt, US_Constitution.txt)
├── Reports/     (EPA report, NIST Framework, OWASP Guide)
└── Technical/   (RFC2616, RFC7231)
```

### Special Paths
- User trash: `/okm:trash/okmAdmin/`
- Personal folder: `/okm:personal/okmAdmin/`
- Root: `/okm:root/`

## CRITICAL: Xauthority Fix for Mouse Events

GDM stores the X11 auth cookie at `/run/user/1000/gdm/Xauthority`, but the framework's SSH-based X auth setup creates an empty `~/.Xauthority`. Without fixing this:
- **Keyboard events via xdotool**: WORK (sent to focused window)
- **Mouse events via xdotool**: DO NOT REACH Firefox content

**Fix** (must be in both `setup_openkm.sh` and `task_utils.sh`):
```bash
cp /run/user/1000/gdm/Xauthority /home/ga/.Xauthority
chown ga:ga /home/ga/.Xauthority
```

After this fix, Firefox must be restarted for mouse events to work. The fix_xauthority function in task_utils.sh runs automatically when sourced.

## Common Issues
| Issue | Solution |
|-------|----------|
| Docker not installed | Install `docker.io` as separate apt-get command |
| HTTP 415 on folder creation | Use `Content-Type: application/json` with raw path body |
| HTTP 500 on document upload | Ensure parent folder exists first |
| HTTP 405 on addKeyword | Use POST method with query params, not PUT |
| HTTP 404 on /OpenKM/login | Use `/OpenKM/login.jsp` instead |
| Firefox shows restore dialog | Delete `.parentlock` and `sessionstore*` before launch |
| Firefox save password prompt | Set `signon.rememberSignons=false` in user.js |
| Mouse clicks don't reach Firefox | Copy GDM Xauthority to ~/.Xauthority, restart Firefox |
| xdotool clicks on GWT tree | Click on tree item text, then use Down arrow to navigate |
