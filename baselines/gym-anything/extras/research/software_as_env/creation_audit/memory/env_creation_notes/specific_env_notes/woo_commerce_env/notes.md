> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# WooCommerce Environment Notes

## Architecture

WooCommerce runs as a WordPress plugin on top of a native Apache/PHP stack. The database is MariaDB running inside Docker. This follows the same hybrid pattern as Magento:

- **Database**: MariaDB 10.6 via Docker container (`woocommerce-mariadb`)
- **Web Server**: Apache 2 + PHP 8.2 (native on VM)
- **CMS**: WordPress (installed via WP-CLI)
- **Plugin**: WooCommerce (installed via WP-CLI)
- **Theme**: Storefront (official WooCommerce theme)
- **Browser**: Firefox with pre-configured profile

## Key Differences from Magento

1. **Simpler installation**: WordPress + WP-CLI is much faster than Magento's Composer-based install
2. **No Elasticsearch needed**: WooCommerce uses MySQL-based search (simpler Docker setup)
3. **WP-CLI for admin tasks**: WP-CLI replaces Magento's bin/magento CLI
4. **WordPress database schema**: Uses wp_posts/wp_postmeta (EAV-like) instead of Magento's entity tables
5. **REST API via basic auth**: WooCommerce REST API at `/wp-json/wc/v3/`
6. **Coupons as post type**: WooCommerce stores coupons as `shop_coupon` post type

## Database Schema

WooCommerce stores data in the standard WordPress database schema:

- **Products**: `wp_posts` (post_type='product') + `wp_postmeta` for attributes
- **Categories**: `wp_terms` + `wp_term_taxonomy` (taxonomy='product_cat')
- **Customers**: `wp_users` + `wp_usermeta` (role='customer')
- **Coupons**: `wp_posts` (post_type='shop_coupon') + `wp_postmeta`
- **Orders**: `wp_posts` (post_type='shop_order') + `wp_postmeta`

### Key Meta Keys

| Entity | Meta Key | Description |
|--------|----------|-------------|
| Product | `_sku` | Product SKU |
| Product | `_regular_price` | Regular price |
| Product | `_sale_price` | Sale price |
| Product | `_stock` | Stock quantity |
| Product | `_stock_status` | In stock/Out of stock |
| Coupon | `discount_type` | percent/fixed_cart/fixed_product |
| Coupon | `coupon_amount` | Discount value |
| Coupon | `usage_limit` | Max uses per coupon |
| Coupon | `minimum_amount` | Min order amount |
| User | `first_name` | Customer first name |
| User | `last_name` | Customer last name |
| User | `wp_capabilities` | User role |

## Credentials

- **WordPress Admin**: admin / Admin1234!
- **Database**: wordpress / wordpresspass (root: rootpass)
- **VM User**: ga / password123

## Data Seeding

Products are seeded via two methods:
1. **WooCommerce sample data XML** (47 items) imported via `wp import` + wordpress-importer plugin
2. **WP-CLI commands** for additional products, coupons, and customers

Initial REST API seeding approach failed due to `.htaccess` issues (see Known Issues).
WP-CLI seeding is more reliable because it bypasses the web server entirely.

### Pre-loaded Data

- 30 products (47 XML imports, some duplicates + 12 WP-CLI products)
- 3 coupons (WELCOME10, FREESHIP, SAVE20)
- 3 customers (John Doe, Jane Smith, Mike Wilson)

## Verification Approach

All tasks use a **hybrid programmatic + VLM pattern** (70/30 split):

1. **export_result.sh** (runs in VM): Queries MariaDB via Docker, exports JSON to `/tmp/`
2. **verifier.py** (runs on host): Uses `copy_from_env` to read JSON, evaluates criteria
3. **VLM trajectory checks** (30 pts): Framework-captured screenshots analyzed with query_vlm
   - Process verification (15 pts): Multiple sampled trajectory frames
   - Final state verification (10 pts): Final screenshot analysis
   - Cross-validation (5 pts): Programmatic + VLM agreement

### Query Patterns

Database queries go through Docker:
```bash
docker exec woocommerce-mariadb mysql -u wordpress -pwordpresspass wordpress -N -B -e "SQL"
```

### Fallback Search Strategy

Each export script follows a progressive search:
1. Exact match (case-insensitive)
2. Partial/LIKE match
3. Name-based search
4. Newest record (if count increased)

## Tasks

### create_product
- Creates a new simple product with specific name, SKU, price, and category
- Verifies: product existence, SKU match, name match, price match

### add_coupon
- Creates a percentage discount coupon with specific code, amount, and restrictions
- Verifies: coupon existence, code match, discount type, amount, usage limits

### create_customer_account
- Creates a new customer user account with specific details
- Verifies: customer existence, email match, first/last name, username

## Known Issues & Gotchas

1. **WP-CLI requires --allow-root**: All wp commands need this flag when running as root
2. **Permalink structure**: Must be set to non-plain for REST API to work
3. **WooCommerce setup wizard**: Dismissed via wp option updates to avoid blocking the agent
4. **WordPress application passwords**: May need to be enabled for REST API auth
5. **Docker table prefix**: WordPress tables use `wp_` prefix by default
6. **Coupon codes are stored lowercase**: WooCommerce normalizes coupon codes to lowercase in `post_title`
