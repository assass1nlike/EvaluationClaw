> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Drupal Commerce Environment - Creation Notes

## Overview

Drupal Commerce is an e-commerce framework built on Drupal CMS. This environment runs Drupal 10.x with Commerce 3.x, MariaDB 10.6 (via Docker), Apache 2, and PHP 8.3 inside a QEMU VM.

## Installation Quirks

### 1. Composer Minimum Stability (CRITICAL)

Drupal Commerce 3.x depends on `drupal/inline_entity_form`, which is only available at RC (Release Candidate) stability. By default, Composer's `minimum-stability` is set to `stable`, which causes the install to fail.

**Fix:** Set minimum-stability to RC before requiring Commerce:
```bash
composer config minimum-stability RC
composer require drupal/commerce -W --no-interaction
```

The `-W` (--with-all-dependencies) flag is also required to allow Composer to update all transitive dependencies.

### 2. Pre-start Hook Timeout

The `pre_start` hook (install script) runs Composer operations that download significant amounts of data:
- `composer create-project drupal/recommended-project` (~50-80MB)
- `composer require drush/drush` (~10-20MB)
- `composer require drupal/commerce -W` (~20-30MB)

On slow networks, this can exceed the QEMU runner's SSH exec timeout (default 600s). The script was designed to install Drush first (smaller, faster) before Commerce.

**Mitigation:** If timeouts occur, the VM remains running and installation can be completed manually via SSH, or the timeout can be increased in the runner configuration.

### 3. PHP 8.3 PPA Requirement

Drupal 10.x/11.x requires PHP 8.1+. The base Ubuntu image may not include PHP 8.3, so the `ondrej/php` PPA is added:
```bash
add-apt-repository -y ppa:ondrej/php
```

## Authentication Pattern: Drush ULI

### Problem
Drupal requires session-based authentication. A custom auto-login module was initially attempted but failed due to cookie handling issues in the automated Firefox launch.

### Solution: Drush One-Time Login (ULI)
Drush provides `uli` (user-login) which generates a one-time login URL:
```bash
LOGIN_URL=$($DRUSH uli --uri=http://localhost --no-browser --uid=1)
```

This URL auto-authenticates the admin user on first visit. Combined with a `?destination=` parameter, it redirects to the desired page:
```bash
LOGIN_DEST="${LOGIN_URL}?destination=admin/commerce"
su - ga -c "DISPLAY=:1 firefox '$LOGIN_DEST' &"
```

This approach is used in:
- `setup_drupal_commerce.sh` (post_start hook) - Initial Firefox launch
- `task_utils.sh` - `ensure_drupal_shown()` fallback function
- Each `setup_task.sh` does NOT need to re-login since the Firefox session persists

### Important Note
The ULI link is single-use. Once the admin session is established in Firefox, subsequent navigations within the same Firefox session maintain the authenticated state via session cookies.

## Permission Granting

Drupal Commerce uses granular permissions. The admin user must have the `administrator` role with Commerce permissions explicitly granted:

```bash
$DRUSH role:perm:add administrator \
    "administer commerce_store,access commerce administration pages,administer commerce_order,administer commerce_product,administer commerce_product_type,administer commerce_promotion,administer commerce_payment,access commerce_order overview,view commerce_product,create default commerce_product,update any default commerce_product,delete any default commerce_product,manage default commerce_product_variation,view own commerce_order,manage default commerce_order_item"

$DRUSH user:role:add administrator admin
```

Without this, the admin user gets "Access denied" on Commerce pages even though they created the site.

## Data Seeding Approach

### PHP Scripts via Drush
Data is seeded using PHP scripts executed via `drush php:script`. This is more reliable than raw SQL because it uses Drupal's entity API, which handles:
- Entity field validation
- Entity relationships (product ↔ variation, promotion ↔ coupon)
- Store assignments
- Cache invalidation

The scripts are mounted read-only and copied to `/tmp/` before execution:
```bash
cp /workspace/scripts/seed_products.php /tmp/seed_products.php
$DRUSH php:script /tmp/seed_products.php
```

### Store Creation
The store entity is created inside `seed_products.php`. Commerce requires at least one store before products can be created. The store is created with `is_default: TRUE` so all products are automatically assigned to it.

## Database Access Pattern

MariaDB runs in a Docker container named `drupal-mariadb`. All database queries go through Docker exec:
```bash
docker exec drupal-mariadb mysql -u drupal -pdrupalpass drupal -N -e "QUERY"
```

This is wrapped in the `drupal_db_query()` function in `task_utils.sh` with error handling and debug logging.

## Service Startup Order

1. Docker daemon (already enabled in pre_start)
2. MariaDB container via `docker-compose up -d`
3. Wait for MariaDB readiness (polling `mysqladmin ping`)
4. Drupal site installation via Drush
5. Commerce module enabling
6. Data seeding
7. Apache restart
8. Wait for Drupal web readiness (polling HTTP status)
9. Firefox launch with Drush ULI link

## Firefox Profile Configuration

Key Firefox preferences set to prevent UI interference during agent interaction:
- `browser.aboutwelcome.enabled: false` - No welcome page
- `browser.startup.homepage_override.mstone: "ignore"` - No "what's new" page
- `signon.rememberSignons: false` - No password save prompts
- `sidebar.revamp: false` / `sidebar.verticalTabs: false` - No sidebar popups
- `browser.startup.homepage: "http://localhost/admin/commerce"` - Commerce admin as homepage

## Task Design Considerations

### create_product
- Navigates to the Products admin page before the agent starts
- Agent needs to: click "+ Add product", fill in title/SKU/price/description, click Save
- Drupal's product form has nested "variation" forms (inline entity form) which can be complex

### create_coupon
- Navigates to the Promotions admin page
- Agent needs to: click "+ Add promotion", set name, configure offer type/amount, enable "Require coupon", add coupon code, click Save
- The promotion form is multi-section with collapsible fieldsets

### add_to_cart
- Navigates to the public product catalog at `/products` (a custom Views page)
- Agent needs to: find the product in the catalog (may need to scroll), click it, click "Add to cart"
- Drupal Commerce does NOT create a public product listing by default; a `product_catalog` View was created in setup to expose products at `/products`
- Products are sorted alphabetically; the target product (Sony WH-1000XM5) may not be on the first screen

## Additional Issues Found in Final Testing

### Store Must Be Created Before Products
The `seed_products.php` script was initially missing store creation. Commerce requires at least one store before products can have store associations. Without a store, the "Add product" admin page shows "Products can't be created until a store has been added." The fix was to add store creation (including the `online` store type) at the beginning of `seed_products.php`.

### MySQL CLI Required for Drush sql:query
Drush's `sql:query` command requires `mysql` or `mariadb` CLI client installed on the host. Without it, Drush's SQL operations silently fail. The `mariadb-client` package must be included in the install script.

### No Default Public Storefront
Drupal Commerce is primarily a backend framework. Unlike WooCommerce which creates a shop page automatically, Commerce does not create any public-facing product listing. A Drupal Views page (`product_catalog`) was created programmatically in the setup script to provide a `/products` URL.

## Debugging Tips

- **Check Drupal logs:** `$DRUSH watchdog:show --count=20`
- **Check Apache error log:** `cat /var/log/apache2/drupal_error.log`
- **Check Docker container:** `docker logs drupal-mariadb`
- **Verify Drupal bootstrap:** `$DRUSH status --field=bootstrap`
- **List enabled modules:** `$DRUSH pm:list --status=enabled --type=module`
- **Clear all caches:** `$DRUSH cr`
- **Database CLI:** `drupal-db-query "SELECT COUNT(*) FROM commerce_product_field_data"`
