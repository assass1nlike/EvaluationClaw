> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenMRS O3 Environment — Creation Notes

## Application Overview
OpenMRS Reference Application 3.0 (O3) is an open-source Electronic Health Records system.
It uses a microservices architecture with 4 Docker services behind an nginx gateway.

## Docker Architecture
- **gateway**: `openmrs/openmrs-reference-application-3-gateway:3.0.0` — nginx reverse proxy (port 80)
- **frontend**: `openmrs/openmrs-reference-application-3-frontend:3.0.0` — React SPA
- **backend**: `openmrs/openmrs-reference-application-3-backend:3.0.0` — Java/Spring (internal 8080)
- **db**: `mariadb:10.11.7` — Database (internal 3306)

## Credentials
- Admin: `admin` / `Admin123`
- DB: user=`openmrs`, pass=`openmrs`, db=`openmrs`

## Key URLs
- SPA: `http://localhost/openmrs/spa`
- Login: `http://localhost/openmrs/spa/login`
- REST API: `http://localhost/openmrs/ws/rest/v1/`
- Health: `http://localhost/openmrs/health/started` (200 = ready)

## CRITICAL: First Boot Takes ~10 Minutes
On first launch, the backend:
1. Initializes the database schema
2. Loads 50+ OpenMRS modules
3. Creates ~50 demo patients
4. This takes 500-600 seconds — poll `/openmrs/health/started` with 600s timeout

## CRITICAL: Patient Identifier Must Be LuhnMod30 Encoded
OpenMRS requires valid identifiers. Direct creation with arbitrary strings fails.

**Solution**: Use the idgen module REST API to generate valid IDs:
```bash
# Get idgen source UUID
IDGEN_SOURCE=$(curl -s -u admin:Admin123 \
    "http://localhost/openmrs/ws/rest/v1/idgen/identifiersource?v=default" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r['results'][0]['uuid'])")

# Generate ID
GEN_ID=$(curl -s -u admin:Admin123 -X POST -H "Content-Type: application/json" \
    -d "{\"generateIdentifiers\":true,\"sourceUuid\":\"$IDGEN_SOURCE\",\"numberToGenerate\":1}" \
    "http://localhost/openmrs/ws/rest/v1/idgen/identifiersource" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('identifiers',[''])[0])")
```

## CRITICAL: extract_uuid Must Read from stdin (Not $1)
In bash subshell calls, piping response through a function:
```bash
# WRONG: $1 is empty when called via pipe
extract_uuid() { echo "$1" | python3 -c "import sys,json; ..."; }
UUID=$(echo "$RESP" | extract_uuid)  # $1 is empty!

# CORRECT: read from stdin directly
extract_uuid() { python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('uuid',''))"; }
UUID=$(echo "$RESP" | extract_uuid)  # stdin gets the JSON
```

## CRITICAL: status messages must go to stderr (not stdout) in subshell captures
```bash
# When calling: P1_UUID=$(create_patient ...)
# Any echo in create_patient goes to P1_UUID variable
# Fix: redirect status messages to stderr
echo "Created patient: $name" >&2
echo "$PATIENT_UUID"  # only the UUID to stdout
```

## Login Flow (Two-Step)
OpenMRS O3 uses a two-step login with location selection:
1. Enter username → click Continue
2. Enter password → click Log in
3. Select location (Outpatient Clinic) → click Confirm

The `ensure_openmrs_logged_in()` function automates this:
- Coordinates for 1920x1080: username≈(996,567), Continue≈(996,640), password≈(996,569), Log in≈(996,641), Outpatient Clinic radio≈(849,452), Confirm≈(994,923)

## Key UUIDs (system defaults, stable across instances)
- OpenMRS ID type: `05a29f94-c0ed-11e2-94be-8c13b969e334`
- idgen source: `8549f706-7e85-4c1d-9424-217d50a2988b`
- Outpatient Clinic location: `44c3efb0-2583-4c80-a79e-1f756a03c0a1`
- Facility Visit type: `7b0f5697-27e3-40c4-8bae-f4049abfb4ed`
- Vitals encounter type: `67a71486-1a54-468f-ac3e-7091a9a79584`
- Encounter role (Unknown): `240b26f9-dd88-4172-823d-4a8bfeb7841f`

## CIEL Concept UUIDs for Vitals
- Weight: `5089AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- Height: `5090AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- BP Systolic: `5085AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- BP Diastolic: `5086AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- Pulse: `5087AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- Temperature: `5088AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- SpO2: `5092AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`

## REST API Patterns
```bash
# Create person
curl -s -u admin:Admin123 -X POST -H "Content-Type: application/json" \
    -d '{"names":[{"givenName":"John","familyName":"Doe","preferred":true}],"gender":"M","birthdate":"1980-01-01"}' \
    "http://localhost/openmrs/ws/rest/v1/person"

# Create patient (requires valid identifier from idgen)
curl -s -u admin:Admin123 -X POST -H "Content-Type: application/json" \
    -d '{"person":"PERSON_UUID","identifiers":[{"identifier":"GEN_ID","identifierType":"ID_TYPE_UUID","location":"LOC_UUID","preferred":true}]}' \
    "http://localhost/openmrs/ws/rest/v1/patient"

# Create visit
curl -s -u admin:Admin123 -X POST -H "Content-Type: application/json" \
    -d '{"patient":"PATIENT_UUID","visitType":"7b0f5697...","startDatetime":"2025-10-15T09:00:00.000+0000","location":"44c3efb0..."}' \
    "http://localhost/openmrs/ws/rest/v1/visit"

# Search patients
curl -s -u admin:Admin123 "http://localhost/openmrs/ws/rest/v1/patient?q=Whitfield&v=default"
```

## Patient Navigation URLs
- Patient chart: `/openmrs/spa/patient/{UUID}/chart`
- Vitals: `/openmrs/spa/patient/{UUID}/chart/Vitals%20%26%20Biometrics`
- Allergies: `/openmrs/spa/patient/{UUID}/chart/Allergies`
- Medications: `/openmrs/spa/patient/{UUID}/chart/Medications`
- Patient registration: `/openmrs/spa/patient-registration`

## 10 Tasks Created
1. `register_patient` — Register Eleanor Vance (DOB 1987-05-14, F, Seattle)
2. `record_vitals` — Record vitals for Dorothy Nguyen
3. `start_visit` — Start Facility Visit for Carlos Reyes
4. `end_visit` — End active visit for Sandra Kowalski (pre-started in setup)
5. `add_allergy` — Add Penicillin/Hives allergy for Marcus Okafor
6. `order_lab_test` — Order CBC for Helen Yamamoto
7. `add_diagnosis` — Add Hypertension diagnosis for Robert Andersen
8. `record_medication` — Add Aspirin 81mg for Patricia Mbeki
9. `update_patient_info` — Update phone for Thomas Fitzgerald
10. `add_appointment` — Schedule appointment for Grace Alvarado

## DB Access
```bash
docker exec openmrs-db-1 mariadb -u openmrs -popenmrs openmrs -N -e "SELECT patient_id, identifier FROM patient_identifier LIMIT 10"
```

## Common Issues During Creation
1. **`docker-compose-plugin` not found**: Ubuntu 22.04 uses `docker-compose-v2` package
2. **LuhnMod30 identifier validation**: Must use idgen module to generate valid IDs
3. **extract_uuid with pipe**: Function must read from stdin, not `$1` positional arg
4. **Status messages captured in UUID vars**: Redirect to stderr with `>&2`
5. **First boot timeout**: Need 600s timeout for health check (10 minutes)
