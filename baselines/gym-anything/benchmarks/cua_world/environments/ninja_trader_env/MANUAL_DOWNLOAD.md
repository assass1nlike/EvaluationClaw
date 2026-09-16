# Manual data download

This environment expects the NinjaTrader 8 installer, which is distributed only through the vendor's account portal.

## File

| Path | Size |
|---|---|
| `data/NinjaTrader.Install.V8.msi` | ~70 MB |

## How to obtain it

1. Create a free account at https://account.ninjatrader.com/
2. Sign in and download **NinjaTrader 8** for Windows.
3. Place the MSI at `data/NinjaTrader.Install.V8.msi`.

If a newer version than 8.0.28.0 is offered, behavior may differ from the project's reference; contact NinjaTrader support for the archived 8.0.28.0 build.

## Verify

```sh
sha256sum data/NinjaTrader.Install.V8.msi
```

Expected sha256 (NinjaTrader 8.0.28.0):
```
cdc027994717c9baa43b47d71681156cacb2f58fbe7da93a0dc79b606289d015
```
