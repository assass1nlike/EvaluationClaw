> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Casebox Environment - Creation Notes

## Application Overview
Casebox is an open-source case management system developed by HURIDOCS and KETSE for human rights organizations. It was sunset in 2020 but self-hosted instances continue to work. Repository: https://github.com/KETSE/casebox

## Architecture Decision: Hybrid (Docker + Native)

### Initial approach (failed): Full Docker-in-QEMU
Building a custom Docker image with PHP, Apache, Solr, and Casebox from source caused the VM to crash. The Docker build consumed too much memory and disk space within the QEMU VM.

### Final approach (working): Docker for MySQL only, native install for everything else
- MySQL 5.7 runs in Docker (fast pull, no build)
- PHP 7.4, Apache 2.4, and Casebox are installed directly in the VM
- Solr is optional (install may fail but basic CRUD works without it)

## Key Technical Issues

### 1. PHP Version Compatibility
Casebox requires PHP 5.5.9-7.4. The VM's base Ubuntu 22.04 ships PHP 8.5. Solution:
- Install PHP 7.4 via `ppa:ondrej/php`
- Use `update-alternatives --set php /usr/bin/php7.4`
- Disable Apache's default PHP module: `a2dismod php8.x`
- Enable PHP 7.4: `a2enmod php7.4`

### 2. Composer 2.9+ Incompatibilities
Modern Composer rejects Casebox's legacy dependencies:
- **Name validation**: Package name must be lowercase; fix with `d['name'] = 'ketse/casebox'`
- **Security audit blocking**: Old packages flagged as insecure; fix with `d['config']['audit'] = {'block-insecure': False}`
- **Missing dev-master constraint**: Remove `satooshi/php-coveralls` from require-dev
- **Post-install script failure**: Use `--no-scripts` flag (SensioDistributionBundle incompatible with new Symfony Process API)
- **Platform check**: Replace vendor/composer/platform_check.php with empty PHP file

### 3. Password Hashing
Casebox uses a custom password scheme:
- Legacy (hash length <= 32): `md5('aero' + password)`
- Modern (hash length > 32): SHA512 encoder

To set admin password:
```bash
ADMIN_HASH=$(php7.4 -r 'echo md5("aero" . "Admin1234!");')
docker exec casebox-db mysql -u casebox -pCaseboxPass123 casebox -e "UPDATE users_groups SET password='${ADMIN_HASH}' WHERE id=1;"
```

### 4. URL Structure
Casebox uses multi-core routing:
- Welcome page: `http://localhost/`
- Core login: `http://localhost/c/default/login`
- Direct auth: `http://localhost/c/default/login/auth?u=root&p=Admin1234!`
- App home: `http://localhost/c/default/`

### 5. Static Asset Symlinks
Casebox stores assets in vendor bundles, not in web/. Must manually link:
```bash
ln -sf /var/www/casebox/vendor/caseboxdev/core-bundle/src/Resources/public/css /var/www/casebox/web/css
ln -sf /var/www/casebox/vendor/caseboxdev/core-bundle/src/Resources/public/js /var/www/casebox/web/js
ln -sf /var/www/casebox/vendor/caseboxdev/core-bundle/src/Resources/public/min /var/www/casebox/web/min
```

### 6. Symfony Console Bug
`bin/console` commands fail with "An option named 'connection' already exists" due to bundle conflicts. Workaround: skip console commands and handle manually.

### 7. Parameters.yml Format
The parameters file MUST include all fields from parameters.yml.dist, especially:
- `core_name`, `locale`, `secret`, `server_name`, `prefix`
- Database connection details with correct host (127.0.0.1 for native, casebox-db for Docker)
- Solr config (can be left empty if not installed)

## Data
- Default schema from `var/backup/cb_default.sql` (23 tables)
- Seed data uses real human rights case names from ECHR, UN Treaty Bodies, and IACtHR
- All case names are from publicly available court records

## Resource Requirements
- CPU: 4 cores
- RAM: 8GB (MySQL container + PHP + Apache)
- Disk: ~2GB for packages, Casebox source, and Docker images
- Network: Required for package installation and Docker Hub
