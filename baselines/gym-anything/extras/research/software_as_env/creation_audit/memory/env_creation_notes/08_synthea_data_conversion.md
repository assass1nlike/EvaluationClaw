# Synthea Data Conversion Guide

## Overview

[Synthea](https://github.com/synthetichealth/synthea) generates realistic synthetic patient data for healthcare applications. This guide covers converting Synthea data to application-specific formats.

## Why Use Synthea?

1. **Medically Realistic** - Coherent patient histories, proper diagnosis-medication relationships
2. **Coded Data** - SNOMED, RxNorm, ICD-10, LOINC codes included
3. **Diverse Demographics** - Multiple races, ethnicities, ages, genders
4. **Free & Open Source** - No licensing concerns for synthetic data

## Synthea CSV Files

Synthea exports data as CSV files:

| File | Contents |
|------|----------|
| `patients.csv` | Demographics (name, DOB, address, SSN, race, ethnicity) |
| `conditions.csv` | Medical problems with SNOMED codes |
| `medications.csv` | Prescriptions with RxNorm codes |
| `allergies.csv` | Allergies with codes |
| `encounters.csv` | Visits and encounters |
| `procedures.csv` | Medical procedures |
| `observations.csv` | Vitals and lab values |
| `immunizations.csv` | Vaccination records |

## Conversion Process

### 1. Load Patient Demographics

```python
def load_synthea_patients(synthea_dir, count=50):
    """Load patients from Synthea CSV"""
    patients_file = Path(synthea_dir) / 'patients.csv'
    patients = []

    with open(patients_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= count:
                break
            # Skip deceased patients for demo
            if row.get('DEATHDATE'):
                continue
            patients.append(row)

    return patients
```

### 2. Clean Synthea Names

Synthea appends numbers to names (e.g., "John847"). Remove them:

```python
import re

def clean_synthea_name(name):
    """Remove numeric suffixes from Synthea names"""
    if not name:
        return ''
    return re.sub(r'\d+$', '', name)
```

### 3. Map Codes and Values

```python
def convert_gender(synthea_gender):
    """Convert Synthea gender to target format"""
    return {'M': 'Male', 'F': 'Female'}.get(synthea_gender, 'Other')

def convert_race(synthea_race):
    """Convert Synthea race codes"""
    race_map = {
        'white': 'white',
        'black': 'black_or_afri_amer',
        'asian': 'asian',
        'native': 'amer_ind_or_alaska_native',
        'other': 'other'
    }
    return race_map.get(synthea_race.lower(), 'decline_to_specify')
```

### 4. Link Related Data

```python
def load_synthea_conditions(synthea_dir, patient_ids):
    """Load conditions for given patients"""
    conditions = {}

    with open(Path(synthea_dir) / 'conditions.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get('PATIENT')
            if pid in patient_ids:
                conditions.setdefault(pid, []).append(row)

    return conditions
```

## Schema Compatibility

### Check Target Schema First

Always verify the target application's schema:

```bash
# Example for MySQL/MariaDB
docker exec db-container mysql -u user -ppass dbname -e "DESCRIBE patients"
```

### Common Schema Differences

| Issue | Example | Solution |
|-------|---------|----------|
| Column name | `create_date` vs `date` | Use correct column name |
| Data type | String 'active' vs Integer 0 | Cast to correct type |
| Required fields | `txDate` NOT NULL | Include all required fields |
| Primary key | `pid` vs `id` | Match key structure |

### Integer vs String Values

```python
# Wrong - string value for integer column
outcome = 'resolved' if end_date else 'active'

# Correct - integer value
outcome = 1 if end_date else 0
```

### NULL Handling

```python
# Wrong - NULL as string
f"'{end_date if end_date else 'NULL'}'"

# Correct - actual NULL
f"'{end_date}'" if end_date else "NULL"
```

## SQL Generation Patterns

### INSERT with Duplicate Handling

```python
sql = f"""INSERT INTO patients (id, fname, lname, dob)
VALUES ({pid}, '{fname}', '{lname}', '{dob}')
ON DUPLICATE KEY UPDATE fname = VALUES(fname);
"""
```

### Escaping Values

```python
def escape_sql(value):
    """Escape single quotes and backslashes for SQL"""
    if value is None:
        return ''
    return str(value).replace("'", "''").replace("\\", "\\\\")
```

## OpenEMR-Specific Notes

### Docker Schema Differences

The Docker OpenEMR image has different schema than manual install:

```python
# Docker schema requires both id and pid
sql = f"""INSERT INTO patient_data (
    id, pid, pubpid, fname, lname, DOB, sex,
    date, regdate  -- Not 'create_date'
) VALUES (
    {pid}, {pid}, 'P{1000+pid}', '{fname}', '{lname}', '{dob}', '{sex}',
    NOW(), NOW()
)"""

# Lists table: outcome is integer
outcome = 1 if end_date else 0  # Not 'resolved' or 'active'

# Prescriptions table: required fields
sql = f"""INSERT INTO prescriptions (
    id, patient_id, drug, rxnorm_drugcode,
    txDate, usage_category_title, request_intent_title  -- Required!
) VALUES (
    {rx_id}, {pid}, '{drug}', '{code}',
    '{start_date}', '', ''
)"""
```

## Command Line Usage

```bash
python synthea_to_openemr.py \
  --synthea-dir /path/to/synthea/csv \
  --output sample_patients.sql \
  --count 50
```

## Data Statistics (Example)

After conversion of 48 Synthea patients:

| Data Type | Count |
|-----------|-------|
| Patients | 46 (living) |
| Medical Conditions | 360 |
| Allergies | 30 |
| Prescriptions | 115 |

## Sample Generated Data

```sql
-- Patient with SNOMED-coded condition
INSERT INTO lists (pid, type, title, diagnosis, outcome)
VALUES (3, 'medical_problem', 'Hypertension', 'SNOMED:38341003', 0);

-- Prescription with RxNorm code
INSERT INTO prescriptions (patient_id, drug, rxnorm_drugcode)
VALUES (3, 'amLODIPine 5 MG Oral Tablet', '329528');
```

## Testing Converted Data

### Verify Patient Load

```bash
docker exec db-container mysql -u user -ppass dbname -e \
  "SELECT COUNT(*) FROM patients"
```

### Verify Data Relationships

```bash
docker exec db-container mysql -u user -ppass dbname -e \
  "SELECT p.fname, c.title
   FROM patients p
   JOIN conditions c ON p.id = c.patient_id
   LIMIT 10"
```

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| "Incorrect integer value" | String in int column | Use integer values |
| "Field doesn't have default" | Missing required field | Add field to INSERT |
| "Duplicate entry" | Primary key conflict | Use ON DUPLICATE KEY |
| "Data truncated" | Value too long | Truncate or use TEXT type |

## Resources

- [Synthea GitHub](https://github.com/synthetichealth/synthea)
- [Synthea Wiki](https://github.com/synthetichealth/synthea/wiki)
- [SNOMED CT Browser](https://browser.ihtsdotools.org/)
- [RxNorm Lookup](https://mor.nlm.nih.gov/RxNav/)
