# Manual data download

SketchUp Make 2017 is auto-fetched by `scripts/fetch_data.sh`. The Skelion plugin must be obtained manually — `skelion.com` only serves the latest version, which differs from the version this env was built against.

## File

| Path | Size |
|---|---|
| `data/Skelion.rbz` | ~6 MB |

## How to obtain it

The reference build is **Skelion v5.5.2**. If you already have an archived copy of `Skelion_skelion_v5.5.2.rbz`, place it at `data/Skelion.rbz`.

If you only have access to a newer Skelion build (e.g., from https://skelion.com/en/download.htm), the env will install but may behave differently in tasks — adjust verifiers accordingly.

## Verify

```sh
sha256sum data/Skelion.rbz
```

Expected sha256 (Skelion v5.5.2):
```
93fa7983ccb5f7fc8ce2df58ddab09badd9c894954c70ec53ada380360468797
```
