> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenMaint Environment - Creation Notes

## Installation Strategy

- Deployed OpenMaint using Docker-in-QEMU (required by this host setup).
- Used maintained deployment artifacts for `openmaint-2.4-4.1.0` with:
  - `postgis/postgis:17-3.5-alpine`
  - `itmicus/cmdbuild:om-2.4-4.1.0`
- Kept `CMDBUILD_DUMP=demo.dump.xz` to load realistic pre-seeded data from upstream-maintained demo content.

## Service Timing

Observed on live run (`2026-02-14`):

- Pre-start (install packages and tooling): included in environment setup, no hook failure.
- Post-start container health:
  - `openmaint_db` healthy immediately after compose start
  - `openmaint_app` healthy in ~45s after startup
- Full environment setup (pre_start + post_start + pre_task): ~169s in the measured run.

## Startup/Health Notes

- `openmaint_app` health check can remain in `starting` during first Tomcat/bootstrap cycle.
- HTTP polling on `http://localhost:8090/cmdbuild/ui/` is reliable as final readiness signal.
- Firefox first-run prompts must be disabled via profile preferences to avoid task interference.
- Repeated fresh VM runs may hit Docker Hub unauthenticated pull limits for `itmicus/cmdbuild:om-2.4-4.1.0`; authenticated pulls or checkpoint caching reduce this risk.
- Optional mitigation is implemented: if `/workspace/config/dockerhub_login.env` exists with `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, post-start performs `docker login` before `docker-compose up -d`.
- No credentials are stored in-repo; use `config/dockerhub_login.env.example` as the template and supply the real file at runtime if needed.

## Data Notes

- Demo OpenMaint database is initialized through `CMDBUILD_DUMP=demo.dump.xz`.
- Runtime check recorded `729` public tables, indicating full seeded schema/data instead of toy handcrafted inserts.

## Task Start State Notes

Task: `login_to_openmaint_and_open_buildings`

- Pre-task hook kills existing Firefox, relaunches OpenMaint URL, and captures `/tmp/task_start_screenshot.png`.
- This keeps task entry deterministic and places the agent on the intended login/start page.
- Live interactive completion on `2026-02-14` confirmed task path end-to-end: login as `admin/admin` and open `/#classes/Building/cards` with demo building rows visible.
- VM resolution was confirmed as `1920x1080` (`xdpyinfo`), which is relevant when scaling coordinates from 1280x720-normalized VLM outputs.

## Verification Notes

- `verifier.py` is a framework-compatibility stub (external VLM evaluators perform actual scoring).
- Evidence artifacts are stored in `benchmarks/cua_world/environments/openmaint_env/evidence_docs/`.
