> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Apache OFBiz Environment - Creation Notes

## Application Overview

Apache OFBiz is an open-source ERP system with modules for accounting, order management, product catalog, manufacturing, HR, and CRM. Version 24.09 is used.

## Installation Approach

- **Docker-in-QEMU** using the official `ghcr.io/apache/ofbiz:release24.09-plugins-snapshot` image
- Demo data loaded via `OFBIZ_DATA_LOAD=demo` environment variable
- OFBiz starts its own embedded Derby database (no external DB needed)
- Ports: 8443 (HTTPS), 8080 (HTTP, redirects to HTTPS)

## Critical Gotchas

### 1. Self-Signed SSL Certificate
OFBiz forces HTTPS (the `no.http=Y` setting in `url.properties`). Modifying this config inside the Docker container does NOT work because the redirect is enforced elsewhere.

**Solution**: Accept the SSL cert in Firefox using the developer console:
```javascript
document.getElementById("advancedButton").click()
document.getElementById("exceptionDialogButton").click()
```

Using `cert_override.txt` or `certutil` did NOT work reliably. The browser console approach is the only method that consistently bypasses the SSL warning.

### 2. Health Check Returns 401
OFBiz returns HTTP 401 (Unauthorized) for unauthenticated requests to module URLs. The health check polling must accept 401 as a valid "ready" response:
```bash
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "401" ]; then
    echo "OFBiz is ready"
fi
```

### 3. Per-Module Sessions
Each OFBiz web module (accounting, ordermgr, catalog, etc.) maintains its own session. Logging into one module does NOT automatically authenticate you for others.

**Solution**: Use URL-based authentication when navigating between modules:
```
https://localhost:8443/ordermgr/control/main?USERNAME=admin&PASSWORD=ofbiz&JavaScriptEnabled=Y
```

### 4. Firefox Extensions Sidebar
Firefox shows an "Extensions" sidebar panel on first launch. Suppress it with:
```javascript
user_pref("sidebar.visibility", "hide-sidebar");
user_pref("sidebar.main.tools", "");
user_pref("extensions.getAddons.showPane", false);
```

### 5. Demo Data Loading Time
First container start takes ~60 seconds to load seed + demo data. Subsequent starts (if container is just stopped/started) are faster since data persists in the container.

### 6. Order Entry URL
The correct URL for the order entry form is `/ordermgr/control/orderentry` (NOT `/ordermgr/control/entry`).

## Demo Data Reference

### Default Users
- admin / ofbiz (Administrator)
- DemoCustomer / ofbiz (Customer)
- DemoSupplier / ofbiz (Supplier)

### Key Products
- GZ-1000: Tiny Gizmo ($9.99)
- GZ-2644: Round Gizmo ($38.40)
- WG-1111: Micro Chrome Widget ($59.99)
- WG-5569: Tiny Chrome Widget ($48.00)
- WG-9943: Giant Widget ($440.00)

### Key Parties
- Company: Default organization
- DemoCustCompany: Demo customer company
- DemoSupplier: Demo supplier
- AcctBuyer: Accounting buyer

### Module URLs
- Accounting: `/accounting/control/main`
- Order Manager: `/ordermgr/control/main`
- Catalog: `/catalog/control/main`
- Party Manager: `/partymgr/control/main`
- Manufacturing: `/manufacturing/control/main`
- Facility: `/facility/control/main`

## Resource Requirements
- CPU: 4 cores
- RAM: 8 GB (OFBiz JVM + Docker + Firefox)
- Disk: ~2 GB (Docker image)
- Network: Required for Docker image pull
