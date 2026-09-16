> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# BTCPay Server Environment - Creation Notes

## Overview
BTCPay Server is a self-hosted, open-source Bitcoin payment processor. The environment runs in regtest mode with Docker Compose inside a QEMU VM.

## Stack
- **btcpayserver/btcpayserver:2.3.7** - Main web application (ASP.NET/Blazor)
- **nicolasdorier/nbxplorer:2.5.30** - Bitcoin UTXO tracker connecting BTCPay to bitcoind
- **btcpayserver/bitcoin:29.1** - Bitcoin Core node (regtest mode)
- **postgres:16-alpine** - Database for BTCPay and NBXplorer

## Critical Gotchas

### 1. Snap Firefox + xdotool + Root
**Problem**: Hooks run as root, but snap Firefox only accepts keyboard input from the owning user (ga). xdotool can read window titles as root, but keystrokes are silently dropped.

**Solution**: Write a temp script and execute via `su - ga -c "bash /tmp/login_script.sh"`. This is the only reliable way to interact with snap Firefox from hook scripts.

### 2. NBXplorer Authentication
**Problem**: BTCPay Server fails with `401 Unauthorized` when connecting to NBXplorer. Error: `BTC: NBXplorer error 'Response status code does not indicate success: 401 (Unauthorized).'`

**Solution**: Set `NBXPLORER_NOAUTH=1` in NBXplorer's environment variables. In production, cookie-based auth is shared via volume mounts, but for regtest this is unnecessary.

### 3. Docker Compose v2 Plugin
**Problem**: `docker-compose-plugin` package is not available in Ubuntu 22.04's default repos. `apt-get install -y docker-compose-plugin` fails.

**Solution**: Download the binary directly:
```bash
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL "https://github.com/docker/compose/releases/download/v2.29.1/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

### 4. Bitcoin Core 29.x - Descriptor Wallets
**Problem**: `createwallet "default"` with positional args fails with "BDB wallet creation is deprecated".

**Solution**: Use named parameters: `bitcoin-cli -named createwallet wallet_name="default" descriptors=true`

### 5. BTCPay Image Versioning
**Problem**: BTCPay Server Docker images use 2.x.y versioning (not 1.x.y as might be expected). The image `btcpayserver/btcpayserver:1.13.5` does not exist on Docker Hub.

**Correct tags** (as of April 2026):
- btcpayserver/btcpayserver: **2.3.7**
- nicolasdorier/nbxplorer: **2.5.30**
- btcpayserver/bitcoin: **29.1**

### 6. BTC Chain Services Readiness
**Problem**: After BTCPay Server responds on HTTP, the BTC chain services may not yet be available. Wallet generation and invoice creation fail with `{"code":"not-available","message":"BTC-CHAIN services are not currently available"}`.

**Solution**: Wait for NBXplorer to sync blocks before creating wallets/invoices. Poll `/api/v1/health` for `synchronized: true` or check `/api/v1/server/info` for `synchronizedNodes > 0`.

### 7. Login Form Interaction
**Problem**: BTCPay Server's login form (ASP.NET MVC) requires precise F6+Tab navigation to reach form fields in snap Firefox.

**Solution**: The reliable sequence is:
1. Press F5 to refresh the page (ensures clean form state)
2. Wait 5 seconds for page load
3. Press F6 to focus page content
4. Press Tab to reach email field
5. Type email character-by-character with 0.03s delays
6. Tab to password field
7. Type password character-by-character
8. Press Enter

### 8. No `set -e` in Setup Scripts
**Problem**: `set -e` causes the post_start script to exit prematurely when service polling functions return non-zero (timeout).

**Solution**: Do not use `set -e` in setup_btcpay.sh. Handle errors explicitly with `|| true` or conditional checks.

## API Reference

### Greenfield API (BTCPay Server)

**Create admin user** (first user only):
```bash
curl -X POST http://localhost/api/v1/users \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"Pass123!","isAdministrator":true}'
```

**Generate API key**:
```bash
curl -X POST http://localhost/api/v1/api-keys \
  -u "email:password" \
  -H "Content-Type: application/json" \
  -d '{"permissions":["unrestricted"]}'
```

**Create store**:
```bash
curl -X POST http://localhost/api/v1/stores \
  -H "Authorization: token $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Store Name","defaultCurrency":"USD"}'
```

**Generate hot wallet**:
```bash
curl -X POST http://localhost/api/v1/stores/$STORE_ID/payment-methods/onchain/BTC/generate \
  -H "Authorization: token $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"savePrivateKeys":true,"importKeysToRPC":false,"wordCount":12,"scriptPubKeyType":"Segwit"}'
```

**Create invoice**:
```bash
curl -X POST http://localhost/api/v1/stores/$STORE_ID/invoices \
  -H "Authorization: token $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount":"99.99","currency":"USD","metadata":{"orderId":"ORD-001"}}'
```

**Create payment request**:
```bash
curl -X POST http://localhost/api/v1/stores/$STORE_ID/payment-requests \
  -H "Authorization: token $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"Invoice #123","amount":"500.00","currency":"USD","description":"Details..."}'
```

## Timing

| Phase | Duration |
|-------|----------|
| VM boot + SSH ready | ~20s |
| pre_start (install + docker pull) | ~30s |
| post_start (compose up + setup + login) | ~75s |
| pre_task (login + navigate) | ~28s |
| **Total** | **~135s** |
