#!/bin/bash
# =============================================================================
# NexusOS ISO Build Script
# Builds a custom Linux Mint-based distribution with embedded AI agent support
# =============================================================================
set -euo pipefail

# Defaults
MINT_VERSION="22"
MINT_EDITION="cinnamon"
MINT_ARCH="64bit"
WORK_DIR="./work"
OUTPUT=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[NexusOS]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --mint-version)  MINT_VERSION="$2";  shift 2 ;;
        --mint-edition)  MINT_EDITION="$2";  shift 2 ;;
        --work-dir)      WORK_DIR="$2";      shift 2 ;;
        --output|-o)     OUTPUT="$2";        shift 2 ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "  --mint-version VERSION   Linux Mint version (default: 22)"
            echo "  --mint-edition EDITION   Edition: cinnamon|mate|xfce (default: cinnamon)"
            echo "  --work-dir DIR           Working directory (default: ./work)"
            echo "  --output FILE            Output ISO path"
            exit 0 ;;
        *) err "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$OUTPUT" ]]; then
    OUTPUT="./out/nexus-os-${MINT_VERSION}.iso"
fi

MINT_ISO_URL="https://mirrors.kernel.org/linuxmint/stable/${MINT_VERSION}/linuxmint-${MINT_VERSION}-${MINT_EDITION}-${MINT_ARCH}.iso"
MINT_ISO="${WORK_DIR}/base.iso"
EXTRACT_DIR="${WORK_DIR}/extract"
SQUASH_DIR="${WORK_DIR}/squashfs"
CHROOT_DIR="${WORK_DIR}/chroot"

# ---------------------------------------------------------------------------
# Phase 1: Download base ISO
# ---------------------------------------------------------------------------
phase_download() {
    log "Phase 1: Downloading Linux Mint ${MINT_VERSION} ${MINT_EDITION}..."

    mkdir -p "$WORK_DIR"

    if [[ -f "$MINT_ISO" ]]; then
        log "Base ISO already exists, skipping download."
        return
    fi

    log "Downloading from: $MINT_ISO_URL"
    wget --progress=bar:force -O "$MINT_ISO" "$MINT_ISO_URL" || {
        err "Failed to download ISO. Check your internet connection and Mint version."
        err "You can also manually place a Linux Mint ISO at: $MINT_ISO"
        exit 1
    }
    log "Download complete."
}

# ---------------------------------------------------------------------------
# Phase 2: Extract ISO contents
# ---------------------------------------------------------------------------
phase_extract() {
    log "Phase 2: Extracting ISO contents..."

    mkdir -p "$EXTRACT_DIR"
    mkdir -p "$SQUASH_DIR"

    # Mount and copy ISO contents
    local mount_point="${WORK_DIR}/mnt"
    mkdir -p "$mount_point"
    mount -o loop "$MINT_ISO" "$mount_point"
    rsync -a "$mount_point/" "$EXTRACT_DIR/"
    umount "$mount_point"
    rmdir "$mount_point"

    # Extract squashfs filesystem
    log "Extracting squashfs (this takes a few minutes)..."
    unsquashfs -f -d "$CHROOT_DIR" \
        "$EXTRACT_DIR/casper/filesystem.squashfs"

    log "Extraction complete."
}

# ---------------------------------------------------------------------------
# Phase 3: Customize the chroot environment
# ---------------------------------------------------------------------------
phase_customize() {
    log "Phase 3: Customizing NexusOS environment..."

    # Mount necessary filesystems for chroot
    mount --bind /dev    "$CHROOT_DIR/dev"
    mount --bind /run    "$CHROOT_DIR/run"
    mount -t proc proc   "$CHROOT_DIR/proc"
    mount -t sysfs sys   "$CHROOT_DIR/sys"
    mount -t devpts devpts "$CHROOT_DIR/dev/pts"

    # Copy DNS config
    cp /etc/resolv.conf "$CHROOT_DIR/etc/resolv.conf"

    # Copy NexusOS source and config into chroot
    mkdir -p "$CHROOT_DIR/opt/nexus"
    cp -r "$SCRIPT_DIR/src"    "$CHROOT_DIR/opt/nexus/"
    cp -r "$SCRIPT_DIR/config" "$CHROOT_DIR/opt/nexus/"

    # Copy overlay files
    if [[ -d "$SCRIPT_DIR/overlay" ]]; then
        cp -r "$SCRIPT_DIR/overlay/"* "$CHROOT_DIR/" 2>/dev/null || true
    fi

    # Run customization inside chroot
    cat << 'CHROOT_SCRIPT' | chroot "$CHROOT_DIR" /bin/bash
set -euo pipefail

export HOME=/root
export LC_ALL=C
export DEBIAN_FRONTEND=noninteractive

echo "=== NexusOS Chroot Customization ==="

# Update package lists
apt-get update

# Install core dependencies
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    sssd \
    sssd-ad \
    sssd-ldap \
    realmd \
    adcli \
    krb5-user \
    samba-common-bin \
    libnss-sss \
    libpam-sss \
    oddjob \
    oddjob-mkhomedir \
    packagekit \
    sqlite3 \
    nginx-light \
    curl \
    jq

# Install NexusOS Python packages
cd /opt/nexus
python3 -m venv /opt/nexus/venv
/opt/nexus/venv/bin/pip install --upgrade pip
/opt/nexus/venv/bin/pip install \
    pydantic click rich tomli \
    aiohttp aiofiles \
    ldap3 msal \
    sqlalchemy aiosqlite

# Install nexus-core and nexus-directory
/opt/nexus/venv/bin/pip install /opt/nexus/src/nexus-core
/opt/nexus/venv/bin/pip install /opt/nexus/src/nexus-directory

# Create nexus system user
useradd --system --home-dir /var/lib/nexus --shell /usr/sbin/nologin nexus || true
mkdir -p /var/lib/nexus /var/log/nexus /etc/nexus/certs /run/nexus
chown -R nexus:nexus /var/lib/nexus /var/log/nexus /run/nexus

# Install config
cp /opt/nexus/config/nexus.conf /etc/nexus/nexus.conf
cp /opt/nexus/config/mcp-registry.json /etc/nexus/mcp-registry.json

# Enable services
systemctl enable nexus-core.service || true
systemctl enable nexus-directory.service || true

# Set branding
echo "NexusOS" > /etc/nexus-release
sed -i 's/Linux Mint/NexusOS/g' /etc/lsb-release 2>/dev/null || true
sed -i 's/linuxmint/nexus-os/g' /etc/lsb-release 2>/dev/null || true

# Enable Cinnamon applet and desklet for default user skeleton
mkdir -p /etc/skel/.config/cinnamon/configs
# Add nexus-agents applet to the default panel layout
# Cinnamon reads enabled-applets from dconf; we set the default via override
mkdir -p /usr/share/glib-2.0/schemas
cat > /usr/share/glib-2.0/schemas/90_nexus-os.gschema.override << 'SCHEMA_EOF'
[org.cinnamon]
enabled-applets=['panel1:left:0:menu@cinnamon.org','panel1:left:1:show-desktop@cinnamon.org','panel1:left:2:grouped-window-list@cinnamon.org','panel1:right:0:systray@cinnamon.org','panel1:right:1:xapp-status@cinnamon.org','panel1:right:2:notifications@cinnamon.org','panel1:right:3:printers@cinnamon.org','panel1:right:4:removable-drives@cinnamon.org','panel1:right:5:keyboard@cinnamon.org','panel1:right:6:favorites@cinnamon.org','panel1:right:7:network@cinnamon.org','panel1:right:8:sound@cinnamon.org','panel1:right:9:power@cinnamon.org','panel1:right:10:calendar@cinnamon.org','panel1:right:11:nexus-agents@nexus-os']
SCHEMA_EOF
glib-compile-schemas /usr/share/glib-2.0/schemas/ 2>/dev/null || true

# Clean up
apt-get autoremove -y
apt-get clean
rm -rf /var/cache/apt/archives/*.deb
rm -rf /tmp/*

echo "=== NexusOS customization complete ==="
CHROOT_SCRIPT

    # Unmount chroot filesystems
    umount "$CHROOT_DIR/dev/pts" 2>/dev/null || true
    umount "$CHROOT_DIR/sys"     2>/dev/null || true
    umount "$CHROOT_DIR/proc"    2>/dev/null || true
    umount "$CHROOT_DIR/run"     2>/dev/null || true
    umount "$CHROOT_DIR/dev"     2>/dev/null || true

    log "Customization complete."
}

# ---------------------------------------------------------------------------
# Phase 4: Rebuild the ISO
# ---------------------------------------------------------------------------
phase_rebuild() {
    log "Phase 4: Rebuilding ISO..."

    # Regenerate squashfs
    log "Compressing filesystem (this takes several minutes)..."
    rm -f "$EXTRACT_DIR/casper/filesystem.squashfs"
    mksquashfs "$CHROOT_DIR" "$EXTRACT_DIR/casper/filesystem.squashfs" \
        -comp xz -Xbcj x86 -b 1M

    # Update filesystem size
    printf "$(du -sx --block-size=1 "$CHROOT_DIR" | cut -f1)" \
        > "$EXTRACT_DIR/casper/filesystem.size"

    # Update MD5 checksums
    cd "$EXTRACT_DIR"
    rm -f md5sum.txt
    find . -type f -not -name md5sum.txt -not -path './isolinux/*' \
        -exec md5sum {} \; > md5sum.txt
    cd "$SCRIPT_DIR"

    # Build ISO
    mkdir -p "$(dirname "$OUTPUT")"
    xorriso -as mkisofs \
        -iso-level 3 \
        -full-iso9660-filenames \
        -volid "NexusOS" \
        -output "$OUTPUT" \
        -eltorito-boot isolinux/isolinux.bin \
            -eltorito-catalog isolinux/boot.cat \
            -no-emul-boot \
            -boot-load-size 4 \
            -boot-info-table \
        -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
        -eltorito-alt-boot \
            -e boot/grub/efi.img \
            -no-emul-boot \
            -isohybrid-gpt-basdat \
        "$EXTRACT_DIR"

    log "ISO built successfully: $OUTPUT"
    log "Size: $(du -h "$OUTPUT" | cut -f1)"
}

# ---------------------------------------------------------------------------
# Phase 5: Cleanup
# ---------------------------------------------------------------------------
phase_cleanup() {
    log "Phase 5: Cleanup..."
    # We keep work dir for faster rebuilds; use 'make clean' to remove
    log "Work directory preserved at: $WORK_DIR"
    log "Run 'make clean' to remove build artifacts."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║       NexusOS ISO Build System           ║${NC}"
    echo -e "${CYAN}║   Autonomous Agentic AI Distribution     ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
    echo ""

    if [[ $EUID -ne 0 ]]; then
        err "This script must be run as root (for chroot and mount operations)"
        err "Usage: sudo bash build.sh [OPTIONS]"
        exit 1
    fi

    phase_download
    phase_extract
    phase_customize
    phase_rebuild
    phase_cleanup

    echo ""
    log "========================================="
    log "  NexusOS build complete!"
    log "  ISO: $OUTPUT"
    log "  Boot in a VM to test."
    log "========================================="
}

main "$@"
