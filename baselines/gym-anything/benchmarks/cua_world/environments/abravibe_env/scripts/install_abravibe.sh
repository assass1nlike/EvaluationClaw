#!/bin/bash
set -e

echo "=== Installing GNU Octave and ABRAVIBE Toolbox ==="

export DEBIAN_FRONTEND=noninteractive

# Configure APT for reliability
cat > /etc/apt/apt.conf.d/99custom << 'APT_CONF_EOF'
Acquire::Retries "3";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
APT_CONF_EOF

apt-get update

# Install GNU Octave with GUI and all dependencies
apt-get install -y \
    octave \
    octave-common \
    octave-doc \
    gnuplot \
    gnuplot-x11 \
    liboctave-dev \
    scrot \
    wmctrl \
    xdotool \
    x11-utils \
    imagemagick \
    python3-pip \
    curl \
    wget \
    fonts-dejavu \
    unzip

# Install Octave Forge packages for signal processing
apt-get install -y \
    octave-signal \
    octave-statistics \
    octave-io \
    octave-control || true

echo "=== GNU Octave installed ==="

# =====================================================================
# Install ABRAVIBE toolbox
# =====================================================================
echo "=== Installing ABRAVIBE toolbox ==="

ABRAVIBE_DIR="/usr/share/octave/site/m/abravibe"
mkdir -p "$ABRAVIBE_DIR"

# Copy bundled ABRAVIBE toolbox functions
cp /workspace/data/abravibe_toolbox/*.m "$ABRAVIBE_DIR/"
chmod 644 "$ABRAVIBE_DIR"/*.m

# Add ABRAVIBE to Octave path system-wide
cat > /usr/share/octave/site/m/startup/abravibe_path.m << 'EOF'
% Add ABRAVIBE toolbox to path on startup
addpath('/usr/share/octave/site/m/abravibe');
EOF

echo "ABRAVIBE toolbox installed to $ABRAVIBE_DIR"

# =====================================================================
# Install CWRU bearing dataset (real vibration data)
# Source: Case Western Reserve University Bearing Data Center
#   https://engineering.case.edu/bearingdatacenter/download-data-file
# =====================================================================
echo "=== Installing CWRU bearing dataset ==="

DATA_DIR="/home/ga/Documents/cwru_data"
mkdir -p "$DATA_DIR"

CWRU_BASE="https://engineering.case.edu/sites/default/files"
fetch_cwru() {
    local local_name="$1" remote_id="$2" expected_sha="$3"
    curl -fsSL --retry 3 --retry-delay 5 --max-time 300 \
        -o "$DATA_DIR/${local_name}.mat" \
        "${CWRU_BASE}/${remote_id}.mat"
    echo "${expected_sha}  $DATA_DIR/${local_name}.mat" | sha256sum -c -
}

fetch_cwru normal_97   97  16bf48babcf1c7ac224bc1a81cd9eafdb27e42d5cf559761907e067e8eeadf3c
fetch_cwru ir007_105  105  f80b0ea04fd06b372a0eaec7c056543ea37e4bb4727a5b173d2a5bacd2aa9cab
fetch_cwru ball007_118 118 b00628f8dd8d1d930af77fa465d1e5cdb385fe259489053f91f3680bda7f640e
fetch_cwru or007_130  130  35a095307d0971477049b343a1b5981dde465a58fb7f233ad89b035068c1717d
fetch_cwru ir021_209  209  9f723d6d9d2eba714c6dc50f99321dffa73d8b1e4d3605675b2c2251511eff80

chown -R ga:ga /home/ga/Documents

# Create output directory for plots
mkdir -p /home/ga/plots
chown -R ga:ga /home/ga/plots

echo "=== CWRU bearing dataset installed ==="
echo "=== ABRAVIBE environment installation complete ==="
