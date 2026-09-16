> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Jenkins Environment - Creation Notes

## Installation

- Docker image: `jenkins/jenkins:lts-jdk21` (official LTS with Java 21)
- Pattern: Docker-in-QEMU (same as OpenEMR, FreeScout, GeoServer)
- Admin creds: admin/Admin123! (created via Groovy init script)

## Critical Gotchas

### 1. Setup Wizard Skip = No Plugins
When using `-Djenkins.install.runSetupWizard=false` (via `JAVA_OPTS` env var), Jenkins starts with ZERO plugins installed. This means:
- No Pipeline support (no `workflow-aggregator`)
- No Git plugin
- No Pipeline stage view

**Fix:** Install plugins explicitly in post_start:
```bash
java -jar /tmp/jenkins-cli.jar -s "$JENKINS_URL" -auth "admin:Admin123!" install-plugin workflow-aggregator git pipeline-stage-view
java -jar /tmp/jenkins-cli.jar -s "$JENKINS_URL" -auth "admin:Admin123!" safe-restart
```

### 2. CSRF Token Requires Cookie Jar
Jenkins CSRF protection binds the crumb to the HTTP session. You MUST use a cookie jar:
```bash
# WRONG - crumb without cookies, will get 403
curl -s -u admin:pass "$URL/crumbIssuer/api/json"
CRUMB=$(... extract crumb ...)
curl -u admin:pass -H "Jenkins-Crumb: $CRUMB" -X POST "$URL/createItem?name=job"

# RIGHT - cookie jar links crumb to session
curl -s -u admin:pass -c /tmp/cookies "$URL/crumbIssuer/api/json"
CRUMB=$(... extract crumb ...)
curl -u admin:pass -b /tmp/cookies -H "Jenkins-Crumb: $CRUMB" -X POST "$URL/createItem?name=job"
```

### 3. Job-Level vs Build-Level API
- `/job/NAME/api/json` returns `lastBuild: {"number": 1, "_class": "..."}` - NO `result` or `building` fields
- `/job/NAME/lastBuild/api/json` returns FULL build details including `result`, `building`, `duration`, `timestamp`
- Always use the build-level endpoint when you need build status/result

### 4. Named Docker Volume vs Bind Mount
Named Docker volumes (`jenkins_home:/var/jenkins_home`) are managed by Docker and initialized from the image. Files placed on the host at a path won't be accessible. Must use bind mount:
```yaml
volumes:
  - /home/ga/jenkins/jenkins_home:/var/jenkins_home  # bind mount - host files visible
```

### 5. Groovy Init Script Location
- Scripts go in `jenkins_home/init.groovy.d/`
- They run on FIRST startup only (or when Jenkins detects they're new)
- Must be present BEFORE first container start
- Set ownership to `1000:1000` (jenkins user inside container)

## API Patterns

### Create Freestyle Job
```bash
cat > /tmp/config.xml << 'EOF'
<?xml version='1.1' encoding='UTF-8'?>
<project>
  <description>Job description</description>
  <builders>
    <hudson.tasks.Shell>
      <command>echo "Hello"</command>
    </hudson.tasks.Shell>
  </builders>
</project>
EOF

curl -u admin:Admin123! -b /tmp/cookies -H "Jenkins-Crumb: $CRUMB" \
  -X POST "$URL/createItem?name=MyJob" \
  -H "Content-Type: text/xml" \
  --data-binary @/tmp/config.xml
```

### Create Pipeline Job
```bash
cat > /tmp/config.xml << 'EOF'
<?xml version='1.1' encoding='UTF-8'?>
<flow-definition>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition">
    <scm class="hudson.plugins.git.GitSCM">
      <userRemoteConfigs>
        <hudson.plugins.git.UserRemoteConfig>
          <url>https://github.com/user/repo.git</url>
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
    </scm>
    <scriptPath>Jenkinsfile</scriptPath>
  </definition>
</flow-definition>
EOF
```

### Trigger Build
```bash
curl -u admin:Admin123! -b /tmp/cookies -H "Jenkins-Crumb: $CRUMB" \
  -X POST "$URL/job/MyJob/build"
```

### Check Build Result
```bash
curl -s -u admin:Admin123! "$URL/job/MyJob/lastBuild/api/json" | jq '.result'
# Returns: "SUCCESS", "FAILURE", "UNSTABLE", or null (still building)
```

## Job Type Detection
- Freestyle: `_class` contains `FreeStyleProject`, XML root is `<project>`
- Pipeline: `_class` contains `WorkflowJob`, XML root is `<flow-definition>`

## Timing
- Jenkins container start to API ready: ~5-30 seconds (depends on plugins)
- Plugin installation + restart: ~30-60 seconds
- Simple build execution: ~2-5 seconds
- Total environment boot: ~170 seconds

## Interactive GUI Testing (ask_cua.py + xdotool)

### Save/OK Button Workaround
Jenkins Save and OK buttons at the bottom of forms consistently fail with direct xdotool clicks. The buttons' visual position in screenshots doesn't match their actual X11 clickable position (likely due to browser scrolling state or GNOME panel offsets).

**Reliable workaround:** Use F12 browser console:
```bash
# Open Firefox console
xdotool key ctrl+shift+k
sleep 1
# Click in console input area (ask_cua.py to find coordinates)
xdotool mousemove X Y click 1
sleep 0.5
# For OK button on New Item page:
xdotool type "document.getElementById('ok-button').click()"
xdotool key Return
# For Save button on config pages:
xdotool type "document.querySelector('button[name=Submit]').click()"
xdotool key Return
```

### Coordinate Scaling
- ask_cua.py returns coordinates in 1280x720 space
- Scale to 1920x1080: `actual_x = cua_x * 1920 / 1280`, `actual_y = cua_y * 1080 / 720`
- Example: "New Item" at CUA (106, 156) → xdotool (159, 234)

### Navigation Pattern
- Use Ctrl+L → type URL → Enter for page navigation (more reliable than clicking links)
- Use ask_cua.py for finding specific UI elements (dropdowns, radio buttons, text fields)
- Use xdotool type for text input (no need for ask_cua.py coordinate)

### Jenkins-Specific GUI Notes
- "Pipeline" tab in job config is in the left sidebar, not main content
- "Definition" dropdown defaults to "Pipeline script" - need to change to "Pipeline script from SCM"
- "SCM" dropdown defaults to "None" - need to change to "Git"
- "Build Now" link appears in left sidebar of job page
- After triggering a build, page auto-refreshes to show build status

## Export/Verification
- Export scripts query Jenkins REST API, write JSON to `/tmp/<task>_result.json`
- All export scripts use `jq -n --arg/--argjson` for safe JSON construction (not heredoc+sed)
- Freestyle job config extracted via `/job/NAME/config.xml` (XML format)
- Build command extracted from XML using xmlstarlet or grep
- Pipeline type detected via `_class` field in API JSON response
- Pipeline scriptPath extracted from config XML `<scriptPath>` element
- Build result fetched from build-level API endpoint

## Audit Fixes (2026-02-12)

### Pipeline Jenkinsfile Path
The repo `jenkins-docs/simple-java-maven-app` has Jenkinsfile at `jenkins/Jenkinsfile`, NOT root.
Task description and verifier metadata must specify `jenkins/Jenkinsfile`.

### Pipeline Verifier - 6 Criteria
Added scriptPath verification as 6th criterion with partial credit:
- Exact match: 1.0 points
- Case-insensitive match: 0.75 points
- Contains "Jenkinsfile" but wrong path: 0.25 points

### Admin Credential Race Condition
Post-start script must use retry loop for admin auth verification, not single sleep+check.
Jenkins API may return 403 for several seconds after container start while Groovy init runs.
```bash
for attempt in $(seq 1 12); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u admin:Admin123! "$URL/api/json")
    if [ "$HTTP_CODE" = "200" ]; then break; fi
    sleep 5
done
```

### Snap Firefox Dual-Path
If Firefox is installed via Snap, profile lives at `/home/ga/snap/firefox/common/.mozilla/firefox/`.
Detect with `snap list firefox 2>/dev/null` and write user.js to both paths.
