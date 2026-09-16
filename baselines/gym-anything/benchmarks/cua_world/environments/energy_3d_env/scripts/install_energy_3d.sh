#!/bin/bash
# Do NOT use set -e: allow graceful error handling for optional steps
echo "=== Installing Energy3D ==="

export DEBIAN_FRONTEND=noninteractive

apt-get update -y || true

# X11 / GUI automation tooling and OpenGL/Mesa libs needed by JOGL.
# Energy3D uses reflective access to ClassLoader.sys_paths to inject a native
# library path; that hack only works under Java 8. Java 11+ raises NullPointerException
# in Toolkit.loadLibraries() (verified empirically). Install OpenJDK 8 explicitly.
apt-get install -y --no-install-recommends \
    xdotool wmctrl scrot imagemagick \
    wget curl unzip ca-certificates \
    openjdk-8-jre openjdk-8-jre-headless \
    libgl1-mesa-glx libgl1-mesa-dri libglu1-mesa libegl1-mesa \
    libxrender1 libxtst6 libxi6 libxrandr2 libxxf86vm1 libxcursor1 \
    mesa-utils libfreetype6 fonts-dejavu-core || {
    echo "WARNING: Some packages may have failed to install"
}

# Resolve Java 8 binary path explicitly so the launcher does not depend on
# the system default Java being 8.
JAVA8=$(ls -d /usr/lib/jvm/java-8-openjdk-*/jre/bin/java 2>/dev/null | head -1)
if [ -z "$JAVA8" ] || [ ! -x "$JAVA8" ]; then
    JAVA8=$(ls -d /usr/lib/jvm/java-8-openjdk-*/bin/java 2>/dev/null | head -1)
fi
if [ -z "$JAVA8" ] || [ ! -x "$JAVA8" ]; then
    echo "ERROR: openjdk-8 not found after install"
    ls /usr/lib/jvm/ 2>&1 || true
    exit 1
fi
echo "Using Java 8 at: $JAVA8"
"$JAVA8" -version 2>&1 | head -1

E3D_DIR="/opt/energy3d"
E3D_BASE_URL="https://energy.concord.org/energy3d"
NATIVE_DIR="${E3D_DIR}/native"

mkdir -p "$E3D_DIR/resources/jogl" \
         "$E3D_DIR/resources/ardor3d" \
         "$E3D_DIR/resources/freetts" \
         "$NATIVE_DIR"

# Helper: download with retries
fetch() {
    local url="$1"
    local dest="$2"
    for attempt in 1 2 3; do
        if wget --timeout=120 --tries=1 -q -O "$dest" "$url"; then
            if [ -s "$dest" ]; then
                return 0
            fi
        fi
        echo "  retry $attempt for $url"
        rm -f "$dest"
        sleep 3
    done
    return 1
}

echo "Downloading Energy3D main jar..."
fetch "${E3D_BASE_URL}/energy3d.jar" "${E3D_DIR}/energy3d.jar" || {
    echo "ERROR: failed to download energy3d.jar"
    exit 1
}

UTIL_JARS=(
    "resources/guava-13.0.1.jar"
    "resources/jdom2-2.0.4.jar"
    "resources/poly2tri-core.jar"
    "resources/poly2tri-ardor3d.jar"
    "resources/slf4j-api-1.7.7.jar"
    "resources/jogl/jogl-all.jar"
    "resources/jogl/gluegen-rt.jar"
    "resources/ardor3d/ardor3d-animation.jar"
    "resources/ardor3d/ardor3d-awt.jar"
    "resources/ardor3d/ardor3d-collada.jar"
    "resources/ardor3d/ardor3d-core.jar"
    "resources/ardor3d/ardor3d-effects.jar"
    "resources/ardor3d/ardor3d-jogl.jar"
    "resources/ardor3d/ardor3d-jogl-awt.jar"
    "resources/ardor3d/ardor3d-math.jar"
    "resources/ardor3d/ardor3d-savable.jar"
    "resources/freetts/cmu_time_awb.jar"
    "resources/freetts/cmu_us_kal.jar"
    "resources/freetts/cmudict04.jar"
    "resources/freetts/cmulex.jar"
    "resources/freetts/cmutimelex.jar"
    "resources/freetts/en_us.jar"
    "resources/freetts/freetts.jar"
    "resources/freetts/freetts-jsapi10.jar"
    "resources/freetts/mbrola.jar"
    "resources/freetts/jsapi.jar"
)

echo "Downloading Energy3D dependency jars..."
for rel in "${UTIL_JARS[@]}"; do
    dest="${E3D_DIR}/${rel}"
    mkdir -p "$(dirname "$dest")"
    if ! fetch "${E3D_BASE_URL}/${rel}" "$dest"; then
        echo "WARNING: could not download $rel"
    fi
done

# Download platform native JOGL/gluegen libraries (Linux amd64) and extract .so files
echo "Downloading native JOGL libraries..."
fetch "${E3D_BASE_URL}/resources/jogl/jogl-all-natives-linux-amd64.jar" "/tmp/jogl-natives.jar" || {
    echo "ERROR: failed to download jogl natives"
    exit 1
}
fetch "${E3D_BASE_URL}/resources/jogl/gluegen-rt-natives-linux-amd64.jar" "/tmp/gluegen-natives.jar" || {
    echo "ERROR: failed to download gluegen natives"
    exit 1
}

(cd "$NATIVE_DIR" && unzip -qo -j /tmp/jogl-natives.jar '*.so' || true)
(cd "$NATIVE_DIR" && unzip -qo -j /tmp/gluegen-natives.jar '*.so' || true)

# Energy3D's MainApplication hardcodes `./lib/jogl/native/linux-64` as the
# java.library.path. Mirror NATIVE_DIR at that relative path inside the
# install dir so its post-reflection classloader can still find the native libs.
mkdir -p "${E3D_DIR}/lib/jogl/native"
ln -sfn "${NATIVE_DIR}" "${E3D_DIR}/lib/jogl/native/linux-64"

NATIVE_COUNT=$(ls "$NATIVE_DIR"/*.so 2>/dev/null | wc -l)
echo "Extracted $NATIVE_COUNT native .so libraries"
if [ "$NATIVE_COUNT" -lt 1 ]; then
    echo "ERROR: no native libraries extracted"
    exit 1
fi

# Build classpath string and bake into a launcher
CLASSPATH="${E3D_DIR}/energy3d.jar"
for j in "${E3D_DIR}/resources"/*.jar \
         "${E3D_DIR}/resources/jogl"/*.jar \
         "${E3D_DIR}/resources/ardor3d"/*.jar \
         "${E3D_DIR}/resources/freetts"/*.jar; do
    [ -f "$j" ] || continue
    CLASSPATH="${CLASSPATH}:${j}"
done

cat > "${E3D_DIR}/energy3d.sh" << EOF
#!/bin/bash
# Energy3D launcher - pinned to Java 8 (Energy3D uses reflection on
# ClassLoader.sys_paths that breaks on Java 11+). The application internally
# overrides java.library.path to "./lib/jogl/native/linux-64", so we cd to
# the install dir and provide a symlink at that relative path pointing to
# the extracted native libraries.
export DISPLAY="\${DISPLAY:-:1}"
cd ${E3D_DIR}
exec ${JAVA8} \\
    -Xmx1024m \\
    -Djava.library.path=${NATIVE_DIR} \\
    -Dsun.java2d.opengl=false \\
    -cp "${CLASSPATH}" \\
    org.concord.energy3d.MainApplication "\$@"
EOF
chmod +x "${E3D_DIR}/energy3d.sh"
ln -sf "${E3D_DIR}/energy3d.sh" /usr/local/bin/energy3d

# Sanity check: run with -version style flag won't work (no such flag), so just check classpath
echo "Verifying classpath jars..."
JAR_COUNT=$(echo "$CLASSPATH" | tr ':' '\n' | grep -c '\.jar')
echo "  Jars on classpath: $JAR_COUNT"
if [ "$JAR_COUNT" -lt 15 ]; then
    echo "ERROR: too few jars on classpath ($JAR_COUNT) - install incomplete"
    exit 1
fi

# Download real Energy3D tutorial / example .ng3 files from the official repository
echo "Downloading real Energy3D sample projects from concord-consortium repository..."
SAMPLES_DIR="/opt/energy3d_samples"
mkdir -p "$SAMPLES_DIR"

SAMPLES=(
    "solar-rack-array.ng3"
    "solar-rack-array-row-spacing.ng3"
    "solar-panel-tilt-angle.ng3"
    "solar-panel-azimuth-angle.ng3"
    "solar-canopy.ng3"
    "solar-heat-map.ng3"
    "building-orientation.ng3"
    "building-passive-heating.ng3"
    "building-roof-insulation.ng3"
    "building-shape.ng3"
    "city-block.ng3"
    "guided-design-yield-area-vs-yield-cost.ng3"
)

SAMPLE_BASE="https://raw.githubusercontent.com/concord-consortium/energy3d/master/src/main/resources/org/concord/energy3d/tutorials"
SAMPLE_OK=0
for f in "${SAMPLES[@]}"; do
    if fetch "${SAMPLE_BASE}/${f}" "${SAMPLES_DIR}/${f}"; then
        SZ=$(stat -c%s "${SAMPLES_DIR}/${f}" 2>/dev/null || echo 0)
        echo "  ${f}: ${SZ} bytes"
        SAMPLE_OK=$((SAMPLE_OK + 1))
    else
        echo "  WARNING: failed to download ${f}"
    fi
done

if [ "$SAMPLE_OK" -lt 1 ]; then
    echo "ERROR: no Energy3D sample projects downloaded"
    exit 1
fi
echo "Downloaded $SAMPLE_OK Energy3D sample projects"

chown -R ga:ga "$SAMPLES_DIR"
chmod -R 755 "$E3D_DIR"

# Cleanup
rm -f /tmp/jogl-natives.jar /tmp/gluegen-natives.jar

echo "=== Energy3D installation complete ==="
