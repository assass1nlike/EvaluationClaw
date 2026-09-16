# Manual data download

The sample workbook is auto-fetched by `scripts/fetch_data.sh`. The Oracle Analytics Desktop installer must be obtained manually because it is distributed only through Oracle eDelivery (free Oracle account + OTN License Agreement).

## File

| Path | Size |
|---|---|
| `data/Oracle_Analytics_Desktop_January2026_Win.exe` | ~1.4 GB |

## How to obtain it

1. Sign in (or sign up free) at https://www.oracle.com/.
2. Visit https://www.oracle.com/business-analytics/analytics-desktop.html → **Download**.
3. Accept the OTN License Agreement.
4. Download the **January 2026 Windows release**.
5. Place at `data/Oracle_Analytics_Desktop_January2026_Win.exe`.

If Oracle has rolled past the January 2026 release, request the archived build from Oracle support.

## Verify

```sh
sha256sum data/Oracle_Analytics_Desktop_January2026_Win.exe
```

Expected sha256:
```
39c23201e25a1ff6ece2cccf5ef4f1d1c8a31711f120eca198e50294f81c82f7
```
