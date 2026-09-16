# Manual data download

This environment expects one APK that is not currently distributed via a stable public URL.

## File

| Path | Size |
|---|---|
| `scripts/apks/androidaps-full-debug.apk` | ~93.7 MB |

## How to obtain it

Build from source (AndroidAPS is AGPL-3.0):

```sh
git clone https://github.com/nightscout/AndroidAPS.git
cd AndroidAPS
git checkout 3.3.1.2
./gradlew :app:assembleFullDebug
# Output: app/build/outputs/apk/full/debug/app-full-debug.apk
```

Rename the output to `androidaps-full-debug.apk` and place it at
`scripts/apks/androidaps-full-debug.apk` inside this env.

> A source build will not byte-match the canonical artifact (different keystore + build timestamps), but the env runs correctly with any 3.3.1.2 `fullDebug` build.

## Verify

```sh
sha256sum scripts/apks/androidaps-full-debug.apk
```

Canonical sha256 (matches the project's reference build):
```
45e610ed168d3266a68216f1e8aab16845f897fefa18d9307aa61fdc43c37a7c
```
