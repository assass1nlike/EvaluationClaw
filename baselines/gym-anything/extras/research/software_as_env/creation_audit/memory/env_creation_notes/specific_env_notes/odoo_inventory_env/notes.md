> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Odoo Inventory Environment Notes

## Overview
Odoo Inventory environment using Odoo 17 Community Edition running in Docker.

## Key Technical Details

### Docker-in-QEMU Setup
The environment uses Docker inside the QEMU VM:
- `docker-compose.yml` defines two services: `web` (Odoo) and `postgres` (PostgreSQL)
- Images: `odoo:17`, `postgres:15`
- Data persists in Docker volumes

### Odoo 17 Database Schema Changes

#### JSONB Translatable Fields
Odoo 17 stores translatable fields as JSONB instead of plain text:
```sql
-- Old way (doesn't work in Odoo 17):
SELECT name FROM product_template WHERE name = 'My Product'

-- New way (Odoo 17):
SELECT name->>'en_US' FROM product_template WHERE name->>'en_US' = 'My Product'
```

#### Product Barcode Location
Barcode is stored in `product_product` table, not `product_template`:
```sql
-- Correct query to get product with barcode:
SELECT pt.id, pt.name->>'en_US', pt.default_code, pp.barcode
FROM product_template pt
LEFT JOIN product_product pp ON pp.product_tmpl_id = pt.id
WHERE pt.default_code = 'HELM-IND-001';
```

#### Cost Field (standard_price)
In Odoo 17, `standard_price` (cost) is stored in:
1. `ir_property` table with `res_id = 'product.product,<id>'`
2. Or directly in `product_product.standard_price` (depends on configuration)

Export script now queries both locations:
```sql
-- Try ir_property first
SELECT value_float FROM ir_property WHERE name='standard_price' AND res_id='product.product,<id>'

-- Fallback to direct column
SELECT standard_price FROM product_product WHERE id = <id>
```

### Database Creation

The setup script attempts automated creation via Odoo CLI:
```bash
docker exec odoo-web odoo -d odoo_inventory --init base,stock --stop-after-init
```

If CLI creation fails (due to CSRF or other issues), the agent sees the database creation form.

Database creation form fields:
- Database Name: `odoo_inventory`
- Email: `admin`
- Password: `admin`
- Check "Demo Data" checkbox

### Login Credentials
- Email/Username: `admin`
- Password: `admin`

### Database Access
```bash
# Query via Docker
docker exec odoo-postgres psql -U odoo -d odoo_inventory -c "SELECT COUNT(*) FROM product_template"

# Or using the utility script:
odoo-db-query "SELECT COUNT(*) FROM product_template"
```

### Common Issues and Solutions

#### 1. Firefox Opens to Database Selector Instead of Login
**Cause**: Database doesn't exist yet
**Solution**: Agent should create database through UI or wait for CLI creation

#### 2. Product Name Returned as JSONB
**Cause**: Odoo 17 stores translatable fields differently
**Solution**: Use `name->>'en_US'` in SQL queries

#### 3. Barcode Not Found in product_template
**Cause**: Schema change in Odoo 17
**Solution**: JOIN with `product_product` table

#### 4. Trailing Spaces in Export Data
**Cause**: Shell `cut` command preserves field separators
**Solution**: Pipe through `sed 's/^[[:space:]]*//;s/[[:space:]]*$//'` or use `tr -d '[:space:]'`

#### 5. Product Not Saved After Filling Form
**Cause**: Odoo auto-save might not trigger immediately
**Solution**: Tab to another field or explicitly save

### Verification Strategy

The verification uses STRICT matching (post-audit improvements):

1. **Export Script** (`export_result.sh`): Runs in VM, queries database, saves JSON to `/tmp/task_result.json`
2. **Verifier** (`verifier.py`): Runs on host, uses `copy_from_env` to read JSON, calculates score

#### Strict Matching Rules (Anti-Gaming)
- Product name: **EXACT match only** (no substring matching)
- Internal reference: **EXACT match only**
- Barcode: **EXACT match only**
- adjust_inventory reason: **MUST contain "Annual Stock Count"**
- create_internal_transfer reference: **EXACT match only** (TRANSFER-001)

#### Score Breakdown for create_product (100 points)
- Product exists with EXACT name: 25 points (no partial credit for similar names)
- Product is newly created: 20 points
- Product type is storable: 15 points
- Internal reference matches EXACTLY: 10 points
- Barcode matches EXACTLY: 10 points
- Sales price correct (5% tolerance): 10 points
- Cost correct (5% tolerance): 5 points
- Timestamp check: 5 points

Pass threshold: 65 points AND (product_exists AND newly_created AND correct_type)

#### Score Breakdown for adjust_inventory (105 points total, capped at 100)
- Quantity exactly 50: 35 points
- Quantity changed from initial: 25 points
- Valid product adjusted: 20 points
- Correct location: 10 points
- Reason contains "Annual Stock Count": 10 points (REQUIRED)
- Timestamp check: 5 points

Pass threshold: 60 points AND (quantity_is_50 AND valid_product AND reason_provided)

### Tasks Implemented

1. **create_product**: Create a storable product with EXACT specified details
   - Tests basic Odoo navigation and product creation
   - Difficulty: Easy
   - Requirements: ALL fields must match exactly

2. **create_internal_transfer**: Create internal stock transfer
   - Tests inventory operations
   - Difficulty: Medium
   - Requirements: EXACT reference "TRANSFER-001", different source/dest locations

3. **adjust_inventory**: Adjust inventory quantity to exactly 50
   - Tests inventory adjustments
   - Difficulty: Medium
   - Requirements: Quantity=50, Reason="Annual Stock Count"

### Post-Audit Fixes Applied

**First Audit Fixes:**
1. ✅ Export script now properly extracts cost from Odoo 17
2. ✅ Verifiers use EXACT matching (no substring exploitation)
3. ✅ adjust_inventory verifies reason field
4. ✅ No partial credit for adjusting wrong product
5. ✅ Task descriptions document initial state (database creation page)
6. ✅ Setup script attempts CLI database creation

**Second Audit Fixes:**
7. ✅ Fixed LIKE queries in export scripts - all now use exact matching
   - `create_product/export_result.sh`: Changed `LIKE '%name%'` to `= LOWER('name')`
   - `create_internal_transfer/export_result.sh`: Changed `LIKE '%ref%'` to `= 'ref'`
8. ✅ adjust_inventory now shows target product to agent via HTML info page
   - Setup script opens a Firefox tab with the target product name prominently displayed
   - Includes full instructions for the agent
9. ✅ Reason validation now requires ALL keywords (annual AND stock AND count)
   - Previously only required one keyword (could be gamed with "stock" alone)
   - Now validates: HAS_ANNUAL && HAS_STOCK && HAS_COUNT
10. ✅ Removed misleading screenshots from evidence_docs
    - Deleted 01_inventory_overview.png, 02_products_list.png, 03_product_created.png
    - These showed logged-in state but actual initial state is database creation page
11. ✅ Updated README.md to reflect accurate state

**Third Audit Fixes:**
12. ✅ Improved database creation automation in setup_odoo.sh
    - Uses direct PostgreSQL CREATE DATABASE command (more reliable)
    - Followed by Odoo module initialization with demo data
    - Better error handling and verification
13. ✅ Aligned task.json metadata with verifier requirements
    - adjust_inventory: Changed expected_reason_keywords from 5 keywords to ["annual", "stock", "count"]
    - Added explicit note: "ALL keywords required (annual AND stock AND count)"
14. ✅ Clarified location specification in create_internal_transfer
    - Listed specific acceptable destinations: WH/Stock/Shelf 1, WH/Stock/Shelf 2, WH/Input, WH/Output, etc.
    - Added metadata field: acceptable_destinations array
    - Made clear that any internal location different from source is acceptable
15. ✅ Added proactive volume cleanup in setup_odoo.sh
    - Detects corrupted database state (500 errors)
    - Automatically drops and recreates volumes when corruption detected
    - Handles empty/corrupt database table counts

**Fourth Audit Fixes:**
16. ✅ Fixed adjust_inventory verifier gaming vulnerability
    - CRITICAL: Verifier now requires adjustment on the EXACT TARGET product
    - Adjusting any OTHER product to 50 units gives ZERO credit
    - Changed `valid_product` criterion to `correct_target_product`
    - Added explicit target product ID matching: `adjusted_product_id == target_product_id`
    - Key criteria now: `quantity_is_50 AND correct_target_product AND reason_provided`
17. ✅ Fixed create_internal_transfer verifier gaming vulnerability
    - CRITICAL: Same-location transfers now FAIL (cannot pass with source == destination)
    - Added `locations_valid` to key criteria
    - Key criteria now: `transfer_exists AND newly_created AND is_internal AND locations_valid`
    - No score manipulation possible by creating invalid same-location transfers

**Fifth Audit Fixes:**
18. ✅ Updated ALL task descriptions to mention 500 error possibility and recovery steps
    - Added explicit troubleshooting section for 500 Internal Server Errors
    - Instructions to navigate to database selector and create database manually
    - All three tasks now document three possible initial states: login, database creation, or 500 error
19. ✅ Made adjust_inventory task description self-contained
    - Added guidance on finding target product if Task Information tab not visible
    - Listed common demo products with stock as fallback
    - Explained that target product is shown in a separate browser tab
    - Added step to check all browser tabs for Task Information
20. ✅ Added detailed error recovery steps to all task descriptions
    - Navigate to http://localhost:8069/web/database/selector
    - Create database with specific parameters
    - Wait for completion before proceeding

### Known Issues

#### Base Image Corruption (QEMU COW Overlay)
The QEMU base image may have corrupted Docker volumes from previous failed runs. When this happens:
- Odoo returns 500 Internal Server Error
- Database exists but has no modules installed
- The COW overlay preserves the corrupted state across new environment instances

**Symptoms**:
- HTTP 500 on http://localhost:8069/web/login
- Database exists (SELECT 1 returns 1) but ir_module_module table is empty
- export_result.sh returns empty product counts

**Workaround**:
1. Rebuild the base QEMU image without corrupted Docker volumes
2. Or manually clean up inside the VM:
```bash
cd /home/ga/odoo
docker-compose down -v
docker volume prune -f
docker-compose up -d
# Wait for containers to be healthy, then run module initialization
```

**Root Cause**: The install_odoo.sh (pre_start) pulls Docker images and creates volumes. If Odoo module initialization fails during setup_odoo.sh (post_start), the volumes are left in a corrupted state. Subsequent runs using COW overlay inherit this corrupted state.

**Recommended Fix**: Create a checkpoint/cached image ONLY after successful Odoo initialization with all modules loaded and verified.

### Future Improvements

1. **CRITICAL**: Create a clean base image with properly initialized Odoo database and modules
2. Implement checkpoint caching after successful database initialization
3. Add more complex inventory tasks
4. Add barcode scanning simulation
5. Add purchase/sales order tasks
