> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Ekylibre Farm Management System — Environment Notes

**Status**: FULLY VERIFIED 2026-02-21
**Ekylibre version**: 4.24.0 (main branch as of Feb 2026)
**Ruby**: 2.7.8 | **PostgreSQL**: 13.16 + PostGIS 3.4 | **Rails**: 5.2.8.1

---

## Architecture

- **Containerized**: Ekylibre runs in Docker containers managed by Docker Compose
- **Services**: `ekylibre-web` (Rails/Puma), `ekylibre-db` (postgis/postgis:13-3.4), `ekylibre-redis`
- **Base image**: `ruby:2.7.8-slim` (Debian-based)
- **Multi-tenancy**: Apartment gem 2.2.1 with `use_sql=true`; SecuredSubdomain elevator reads subdomain to switch tenants
- **Demo tenant**: `demo` — accessed at `http://demo.ekylibre.farm:3000`
- **Admin credentials**: `admin@ekylibre.org` / `12345678`

## URL Pattern (CRITICAL)

Ekylibre uses subdomain-based multi-tenancy via the Apartment gem's `SecuredSubdomain` elevator.
- `http://localhost:3000` → NO tenant switch → login fails (no users in public schema)
- `http://demo.ekylibre.farm:3000` → Apartment reads `demo` subdomain → switches to demo tenant
- `/etc/hosts` must have: `127.0.0.1 demo.ekylibre.farm`

## Demo Data

Loaded from [ekylibre/first_run-demo](https://github.com/ekylibre/first_run-demo):
- **Farm**: GAEC JOULIN (Charente-Maritime, France — real farm data)
- **Command**: `RAILS_ENV=production folder=demo name=demo bundle exec rake first_run`
- **Loaders**: 47 total — analyses, animals (171 bovines), base, buildings, entities (99 contacts),
  equipments, land_parcels, productions, products, workers, sales, accountancy (chart of accounts,
  journal entries), bank_statements, cash_transfers, deliveries, interventions, purchases

## Compatibility Fixes (All Required for first_run to Complete)

### Fix 1: apartment.rb — PostGIS in public schema

**Symptom**: `PG::UndefinedFunction: ERROR: function st_asewkt(...) does not exist`
**Root cause**: PostGIS installs all functions in the `public` schema. Apartment's search_path for
a tenant is `demo, postgis, lexicon` — no `public`. Functions like `ST_AsEWKT`, `ST_MakeValid`,
`ST_GeomFromEWKT` are not found.
**Fix** (`/app/config/initializers/apartment.rb`):
```ruby
# Before:
config.persistent_schemas = %w[postgis lexicon]
# After:
config.persistent_schemas = %w[postgis lexicon public]
```
**Effect**: search_path becomes `demo, postgis, lexicon, public` ✓

### Fix 2: shape_corrector.rb — nil guard

**Symptom**: `PG::SyntaxError: ERROR: syntax error at or near ")"` in `ST_CollectionExtract(geom, )`
**Root cause**: `postgis_geometries_extraction` looks up `int_type` from a hash by `geometry_type`.
When `geometry_type = :any` (not in the hash), `int_type` is `nil`. The SQL becomes
`ST_CollectionExtract(geom, )` which is a syntax error.
**Fix** (`/app/app/services/shape_corrector.rb`):
```ruby
int_type = {point: 1, line_string: 2, polygon: 3, geometry_collection: 7}[geometry_type]
return None() if int_type.nil?  # ← Add this line
```

### Fix 3: /usr/share/proj/epsg — PROJ4 CRS definitions file

**Symptom**: `Errno::ENOENT: No such file or directory @ rb_sysopen - /usr/share/proj/epsg`
**Root cause**: PROJ 7.x removed the old text-format `epsg` file (replaced by SQLite `proj.db`).
The `rgeo-proj4` gem (2.0.1) uses `Proj4Data.new('epsg')` which opens `/usr/share/proj/epsg` by
name. The telepac loader transforms EPSG:2154 (Lambert-93) → EPSG:4326 (WGS84) for georeferencing
French cadastral data.
**Fix**: Create `/usr/share/proj/epsg` with PROJ4 text-format CRS definitions.
See `benchmarks/cua_world/environments/ekylibre_env/config/proj_epsg.txt` for the content.
**Key entries**: EPSG:4326 (WGS84), EPSG:2154 (Lambert-93), EPSG:2975 (Reunion), EPSG:2980 (Mayotte)

### Fix 4: freezer.rb — PDF magic bytes detection

**Symptom**: `NoMethodError: undefined method 'strip' for nil:NilClass` in `pdf_extractor.rb:129`
**Root cause**: `pdf_format?` in `paperclip-document-0.0.11` gem uses:
```ruby
File.open(file_path, 'rb', &:readline).to_s =~ /\A\%PDF-\d+(\.\d+)?$/
```
The regex fails on PDFs with Windows `\r\n` line endings. `$` in Ruby regex matches before `\n`
but NOT before `\r`. So `%PDF-1.4\r\n` doesn't match, `pdf_format?` returns false, and
`Docsplit.extract_pdf` is called — which requires LibreOffice/OpenOffice (not installed).
**Fix** (`paperclip-document-*/lib/paperclip/document/processors/freezer.rb`):
```ruby
def pdf_format?
  # Use magic bytes - works regardless of line endings (\n or \r\n)
  File.open(file_path, 'rb') { |f| f.read(8) }.to_s.start_with?('%PDF-')
end
```

### Fix 5: poppler-utils + ghostscript

**Symptom**: `Docsplit::ExtractionFailed: sh: 1: pdftotext: not found`
**Fix**: Install `poppler-utils` and `ghostscript` packages.
`pdftotext` is needed for Docsplit text extraction. `gs` (Ghostscript) is needed by GraphicsMagick
to convert PDF pages to images for attachment thumbnails.

## Working URLs (Ekylibre 4.18.2 / 4.24.0)

| URL | Page |
|-----|------|
| `/backend` | Dashboard (Tableau de bord général) |
| `/backend/animals` | Animal list (171 bovines) |
| `/backend/animals/new?variant_id=152` | New animal form (full) — variant_id=152=Génisse; WITHOUT variant_id shows only Article selector (step 1), full form never appears |
| `/backend/interventions` | Interventions (kanban/list view) |
| `/backend/interventions/new` | New intervention procedure selector |
| `/backend/entities` | Contacts/Tiers (99 from demo data) |
| `/backend/entities/new` | New entity/contact form |
| `/backend/workers` | Workers |
| `/backend/equipments` | Equipment |
| `/backend/products` | Products |
| `/backend/activities` | Activities list (plant_farming: wheat, maize, etc.) |
| `/backend/activities/new` | New activity form |
| `/backend/activity_budgets/new?activity_id=N&campaign_id=N` | New activity budget form (PARAMS REQUIRED — see below) |
| `/backend/purchase_invoices` | Purchase invoices list |
| `/backend/purchase_invoices/new` | New purchase invoice form ("Nouvelle facture") |
| `/backend/journals` | Accounting journals list (also reached via `/backend/journal_entries`) |

**Does NOT exist in 4.18.2**: `/backend/land_parcels`, `/backend/productions`,
`/backend/financial_years`, `/backend/purchases`, `/backend/purchase_orders`

## Activity Budget URL (CRITICAL)

`/backend/activity_budgets/new` WITHOUT params returns HTTP 500:
```
Module::DelegationError: ActivityBudget#activity_name delegated to activity.name,
but activity is nil
```
Root cause: `manage_restfully t3e` calls `@budget.activity_name` in the `new` action,
which delegates to `activity.name`; a brand-new unsaved record has `activity_id: nil`.

**Fix**: Always include `activity_id` and `campaign_id` in the URL:
```
/backend/activity_budgets/new?activity_id=3&campaign_id=8
```
Demo data IDs: activity 3 = "Blé tendre d'hiver" (soft winter wheat), campaign 8 = 2023.

Campaign IDs in demo data: 2=2017, 3=2018, 4=2019, 5=2020, 6=2021, 7=2022, 8=2023.
Activity IDs (all plant_farming): 1=Luzerne, 2=Maïs grain, 3=Blé tendre d'hiver,
4=Sarrasin, 5=Prairie, 6=Orge d'hiver, 7=Soja, 8=Maïs ensilage, 9=Mélange de céréales, 10=Tournesol.

## Docker Compose Setup

`docker-compose.yml` services:
- `web`: `ekylibre-app:local` (built from Dockerfile) — port 3000
- `db`: `postgis/postgis:13-3.4` — PostgreSQL 13 + PostGIS 3.4
- `redis`: `redis:5.0-alpine`

**Why postgis/postgis:13-3.4 not a plain postgres image**: Ekylibre requires PostGIS extensions
for all geometry operations. The `postgis/postgis` image has `CREATE EXTENSION postgis` ready.

## first_run Task Notes

```bash
# Run in ekylibre-web container with demo data volume mounted
RAILS_ENV=production folder=demo name=demo verbose=true bundle exec rake first_run
```

- Takes ~15-30 minutes depending on machine speed
- 47 data files are processed sequentially
- The `georeadings` loader transforms EPSG:2154 coordinates (requires Fix 3)
- The `telepac` loader processes French agricultural parcels XML (requires Fix 3)
- Various PDF document attachments are processed (requires Fixes 4+5)
- The `analyses` loader processes lab analysis PDFs
- The result is stored in `/home/ga/first_run_data/demo/` (cloned from GitHub)
- first_run marks each loader done in `ekylibre_production.preferences` table

## Rails Server Notes

- PID 1 in `ekylibre-web` container runs `bundle exec rails server -b 0.0.0.0 -p 3000 -e production`
- The server stays up continuously after first_run completes (they don't conflict)
- first_run rake task runs in a separate process alongside the live server
- Restart not needed after applying in-container patches (they take effect on next request)

## Apartment Gem + PostGIS: The Core Complexity

The fundamental challenge is that Ekylibre uses:
1. **Apartment** for multi-tenancy: creates a separate PostgreSQL schema per tenant
2. **PostGIS** for geometry: installs functions in `public` schema
3. These two conflict unless `public` is in Apartment's `persistent_schemas`

PostgreSQL's `search_path` determines which schemas are searched for functions. When Apartment
switches to tenant `demo`, it sets `search_path = 'demo, postgis, lexicon'`. Since PostGIS
functions are in `public` (not `postgis`), they're not found. The `postgis` schema in Ekylibre's
config holds the lexicon extension, not the actual PostGIS functions.

**Lesson**: Always add `public` to Apartment's `persistent_schemas` when using PostGIS. The
`postgis.geometry` type references in db/schema.rb also need to be `public.geometry`.

## Tasks (5 implemented)

All tasks use the `http://demo.ekylibre.farm:3000` URL and require the agent to be logged in
as `admin@ekylibre.org` (password: `12345678`).

1. `add_activity_budget` — Add a cost (Dépense) budget item for Blé tendre d'hiver 2023 (click "Ajouter une dépense", NOT "Ajouter une recette")
2. `add_supplier_contact` — Add a new supplier entity with contact details (form already open at /backend/entities/new)
3. `create_purchase_order` — Create a purchase invoice via /backend/purchase_invoices/new (NOT /backend/purchases/new which is 404)
4. `record_intervention` — Record a fertilisation intervention; input product = "Ammonitrate 33 vrac"; land parcels exist (e.g. "A côté de la vigne Blé tendre d'hiver 2017")
5. `register_animal` — Register a new Génisse (heifer); setup pre-selects variant_id=152 to show full form; fields: Nom, Race (Bovin), Né(e) le

## Animals New Form (CRITICAL — Two-Step UI)

`/backend/animals/new` uses `product_form_frame` helper which shows:
- **Without `?variant_id=N`**: ONLY shows "Article" autocomplete selector + Annuler button (step 1)
- **With `?variant_id=152`**: Shows full form immediately — Nom, Race (Bovin), Né(e) le, Date de sortie, Propriétaire initial, Lieu de stockage, Identification section (Numéro d'identification, Numéro de travail, Photo, Description), Généalogie section

Bovine article variants (bos variety):
- variant_id=152: Génisse (heifer/young female cow)
- variant_id=149: Vache (cow/adult female)
- variant_id=151: Veau (calf)
- variant_id=153: Taurillon (young bull)
- variant_id=148: Taureau (bull)

The full form shows "Race" (breed) dropdown defaulting to "Bovin", not a specific Limousin breed — there's no Limousin-specific article in the demo data.

## Interventions and Land Parcels

- 40 total interventions in database across years 2016-2023 (18 in 2017, 5 in each 2018 and 2020, etc.)
- The interventions list defaults to current year (2026) which shows 0 — navigate with `<` arrows to see data
- Land parcels: 164 land parcel products exist (e.g. "A côté de la vigne Blé tendre d'hiver 2017")
- Input product for fertilisation: "Ammonitrate 33 vrac" (product_id=309, type=Matter)
