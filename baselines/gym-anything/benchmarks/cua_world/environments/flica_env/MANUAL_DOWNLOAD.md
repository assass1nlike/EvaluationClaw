# Manual data download

`scripts/fetch_apks.sh` auto-fetches three of the four FLICA split-APKs. One density-split must be obtained manually.

## File

| Path | Size |
|---|---|
| `scripts/apks/config.xxhdpi.apk` | ~61 KB |

## How to obtain it

Install FLICA on a physical Android device with `xxhdpi` screen density, then extract the split APK:

```sh
adb shell pm path com.robert.fcView
# Lists 4 APKs; identify the path ending in split_config.xxhdpi.apk

adb pull <path-to-xxhdpi-split> ./config.xxhdpi.apk
```

Place the result at `scripts/apks/config.xxhdpi.apk`.

## Verify

```sh
sha256sum scripts/apks/config.xxhdpi.apk
```

Expected sha256:
```
0473f477703825924eac26e2442aaedc1375e8957f27e50af0ac16772c97cba1
```
