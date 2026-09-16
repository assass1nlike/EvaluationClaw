> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Magento Open Source Environment Notes

## Architecture

- **Base**: Ubuntu GNOME with systemd (highres)
- **Database**: MariaDB 10.6 via Docker container (`magento-mariadb`)
- **Search**: Elasticsearch 7.17 via Docker container (`magento-elasticsearch`)
- **Web Server**: Apache 2 with PHP 8.2 (native on VM)
- **Application**: Magento Open Source 2.4.7 installed via Composer
- **GUI**: Firefox browser accessing admin panel at `http://localhost/admin`
- **Data**: Seeded via REST API (10 products, 4 categories, 3 customers) - sample data modules require repo.magento.com auth

## Key Credentials

| Service | Username | Password |
|---------|----------|----------|
| Magento Admin | admin | Admin1234! |
| MariaDB (Docker) | magento | magentopass |
| MariaDB Root | root | rootpass |
| VM User | ga | password123 |

## Installation Quirks

### PHP Requirements
- Magento 2.4.7 requires PHP 8.2 or 8.3
- Must install from ondrej/php PPA on Ubuntu (default PHP may be too old)
- Required extensions: bcmath, ctype, curl, dom, gd, intl, mbstring, mysql, simplexml, soap, xsl, zip, xml, opcache
- Memory limit must be at least 2G for CLI operations (setup, compile, deploy)

### Composer Authentication
- Magento Open Source can be installed without authentication keys via GitHub archive download (tar.gz)
- `COMPOSER_ALLOW_SUPERUSER=1` must be exported to avoid interactive prompt when running as root
- Official sample data modules (`magento/module-*-sample-data`) require `repo.magento.com` auth keys
- Data is instead seeded via Magento REST API after installation (10 products, 4 categories, 3 customers)

### Setup Script Ordering
- **Critical**: 2FA modules must be disabled and `setup:upgrade` run BEFORE `setup:di:compile`
- **Critical**: Permissions fix (`chown www-data:www-data`) must happen AFTER `setup:di:compile`
- Data seeding via REST API must happen AFTER Apache starts (needs web server running)
- Order: install -> disable 2FA -> setup:upgrade -> di:compile -> static-content:deploy -> fix perms -> start Apache -> seed data via API

### Two-Factor Authentication
- Magento 2.4+ enforces 2FA by default on admin login
- Must disable `Magento_TwoFactorAuth` and `Magento_AdminAdobeImsTwoFactorAuth` modules for testing
- Command: `php bin/magento module:disable Magento_TwoFactorAuth Magento_AdminAdobeImsTwoFactorAuth`

### Elasticsearch Dependency
- Magento 2.4+ requires Elasticsearch or OpenSearch (MySQL search removed)
- Elasticsearch 7.17.x is the recommended version for Magento 2.4.7
- Must be running before `setup:install` or it will fail
- Healthcheck should verify cluster status is "green" or "yellow"

## Service Timing

| Phase | Expected Duration |
|-------|------------------|
| Docker pull (MariaDB + ES) | 30-60s |
| MariaDB readiness | 15-30s |
| Elasticsearch readiness | 30-90s |
| Magento setup:install | 60-120s |
| Sample data deploy | 60-180s |
| setup:upgrade | 30-60s |
| DI compile | 60-120s |
| Static content deploy | 60-120s |
| Indexer reindex | 30-60s |

Total setup: 5-12 minutes depending on resources.

## Database Schema Notes

### Key Tables

| Table | Purpose |
|-------|---------|
| `catalog_product_entity` | Product base table (entity_id, sku, type_id) |
| `catalog_product_entity_varchar` | Product text attributes (name, etc.) |
| `catalog_product_entity_decimal` | Product decimal attributes (price, etc.) |
| `catalog_category_entity` | Category tree (entity_id, parent_id, level, path) |
| `catalog_category_entity_varchar` | Category text attributes (name, etc.) |
| `catalog_category_entity_int` | Category integer attributes (is_active, include_in_menu) |
| `customer_entity` | Customer records (entity_id, email, firstname, lastname) |
| `customer_group` | Customer groups (customer_group_id, customer_group_code) |
| `sales_order` | Orders (entity_id, increment_id, status, grand_total) |
| `eav_attribute` | EAV attribute definitions (attribute_id, attribute_code) |

### EAV Pattern
Magento uses Entity-Attribute-Value (EAV) model. Product/category/customer attributes are stored across multiple tables:
- `_varchar`: String values
- `_int`: Integer values
- `_decimal`: Decimal values
- `_text`: Long text values
- `_datetime`: Date values

To get a product name:
```sql
SELECT value FROM catalog_product_entity_varchar
WHERE entity_id=<id>
AND attribute_id=(SELECT attribute_id FROM eav_attribute WHERE attribute_code='name' AND entity_type_id=4)
```

### Entity Type IDs
- 1: customer
- 3: catalog_category
- 4: catalog_product
- 5: order

## Verification Gotchas

1. **EAV queries are complex**: Always join through `eav_attribute` to get the correct attribute_id
2. **Store-specific values**: Category/product attributes can have store-specific overrides. Use `store_id=0` for default values
3. **Case sensitivity**: Magento stores SKUs and emails as-entered. Always use `LOWER(TRIM())` for matching
4. **Seed data**: 10 products, 4 categories, 3 customers are pre-loaded. Query by specific SKU/name rather than generic "newest" checks
5. **Admin URL**: The admin panel URL is configurable. Default is `/admin` but can be changed during setup
6. **Cache**: Magento aggressively caches. After creating entities, the storefront may not reflect changes immediately. Use `php bin/magento cache:flush` if needed

## Tasks

### create_product
- Creates a simple product via admin Catalog > Products > Add Product
- Verified by checking `catalog_product_entity` for the SKU and EAV tables for name/price

### add_category
- Creates a subcategory under Default Category via admin Catalog > Categories
- Verified by checking `catalog_category_entity` + `_varchar` for name and `_int` for is_active

### create_customer
- Creates a customer via admin Customers > All Customers > Add New Customer
- Verified by checking `customer_entity` for email, firstname, lastname
