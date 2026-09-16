> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Care2x Environment Notes

## Critical Setup Learnings

### 1. Database Charset Must Be latin1
Care2x's SQL dump uses `latin1_general_ci` collation extensively. Creating the database as `utf8mb4` causes some tables (notably `care_users`) to fail silently during import. Solution: `CREATE DATABASE care2x CHARACTER SET latin1 COLLATE latin1_general_ci;`

### 2. AdodbPdoShim.php Has a Syntax Error
The file at `include/core/AdodbPdoShim.php` has a duplicate `} else { throw $e; }` block that prevents PDO initialization. This forces Care2x to fall back to the legacy ADODB driver, which exhausts PHP memory (even 512MB is insufficient). Fix: Remove the duplicate else block.

### 3. Default User Config Required
The `care_config_user` table MUST have a row with `user_id='default'` containing a valid PHP serialized configuration array. Without it, `UserConfig::_getDefault()` enters an infinite loop querying for a non-existent default record.

### 4. Global Config Required
`care_config_global` must have these entries seeded:
- `language_single` = 1
- `language_default` = en
- `gui_frame_left_nav_width` = 180
- `gui_frame_left_nav_border` = 0
- `timeout_inactive` = 1
- `timeout_time` = 3000

### 5. Database Configuration File
Care2x reads DB credentials from `include/core/inc_init_main.php` (NOT `global_conf/db_config.php`). There's also a copy at `include/helpers/inc_init_main.php` that must be updated.

### 6. Installer Bypass
Care2x checks for `./installer/install.php` at startup. If present, it redirects to the installer. The current GitHub version doesn't have this file (uses `Installer.php` instead), so no action needed.

### 7. hcemd5.php Empty Data Fix
The `decodeMimeSelfRand()` function in `classes/pear/crypt/hcemd5.php` crashes when cookie data is empty. Add: `if(empty($data)||strpos($data,"#")===false){return false;}`

### 8. Smarty Debug Mode
`gui/smarty_template/smarty_care.class.php` has `$this->debug = true;` which must be changed to `false`.

### 9. Login System
- Admin user is stored in `care_users` table with MD5-hashed password
- Password hash: `echo -n "care2x_admin" | md5sum`
- Permission must be `System_Admin` for full access

### 10. Application Architecture
- Care2x uses HTML frames (not modern SPA)
- Main page loads via `index.php` which renders a Smarty frameset template
- Left navigation frame, main content frame, and top frame
- Each module is accessed through the left navigation menu
- Sessions use cookies with encrypted SIDs

### 11. Navigation Frame Fix (nav.php)
The original `indexframe.php` uses Smarty templates which generate PHP 8.1 warnings that cause HTTP 500 status codes. Firefox refuses to render frame content with 500 status, leaving the navigation blank. Fix: deploy a custom `nav.php` that directly queries `care_menu_main` and `care_menu_sub` tables using PDO and renders the dtree.js menu without Smarty.

### 12. Missing Tables on Import
The SQL dump has mixed COLLATE clauses (latin1_general_ci, utf8_unicode_ci). Some tables fail to create silently. Fix: run the import twice - first as-is, second with all COLLATE/CHARSET directives stripped.

### 13. GNOME Dock Interference
The Ubuntu dock on the left side is ~48px wide. When clicking in the Care2x left frame, ensure x-coordinates are > 48 to avoid accidentally clicking dock icons (Files, Terminal, etc.).

### 14. Menu Table Column Names
The `care_menu_main` table uses `nr`, `name`, `url`, `sort_nr`, `is_visible` (NO `m_` prefix). The `care_menu_sub` uses `s_nr`, `s_name`, `s_url`, etc. (WITH `s_` prefix). This inconsistency is a Care2x quirk.

### 15. Data Sources
Patient data MUST use real-world sources (US Census surnames, SSA baby names, real US cities/zips). Synthea-generated data is considered synthetic and should be avoided. The current implementation uses 30 patients with names from Census/SSA, real US cities, correct zip codes, and real area codes.
