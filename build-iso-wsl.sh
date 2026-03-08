#!/bin/bash
# =============================================================================
# NexusOS ISO Build — WSL Quick Build Script
# Run this INSIDE WSL Ubuntu: bash /mnt/e/NexusOS/build-iso-wsl.sh
# The ISO will be output to E:\NexusOS\out\nexus-os.iso
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="/tmp/nexus-build"
OUT_DIR="${SCRIPT_DIR}/out"
MINT_VERSION="22"
MINT_EDITION="cinnamon"
MINT_ARCH="64bit"
MINT_ISO="${WORK_DIR}/base.iso"
EXTRACT_DIR="${WORK_DIR}/extract"
CHROOT_DIR="${WORK_DIR}/chroot"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[NexusOS]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Check root
if [[ $EUID -ne 0 ]]; then
    err "Run with sudo: sudo bash /mnt/e/NexusOS/build-iso-wsl.sh"
    exit 1
fi

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       NexusOS ISO Build System           ║${NC}"
echo -e "${CYAN}║   Building from WSL → Windows output     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Install build tools
# ---------------------------------------------------------------------------
log "Step 1/6: Installing build dependencies..."
apt-get update -qq
apt-get install -y -qq \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-utils \
    rsync \
    wget \
    python3-venv \
    python3-pip \
    > /dev/null 2>&1
log "Dependencies installed."

# ---------------------------------------------------------------------------
# Step 2: Download Linux Mint ISO
# ---------------------------------------------------------------------------
log "Step 2/6: Downloading Linux Mint ${MINT_VERSION}..."
mkdir -p "$WORK_DIR"

if [[ -f "$MINT_ISO" ]]; then
    log "Base ISO already cached at ${MINT_ISO}, skipping download."
else
    MINT_ISO_URL="https://mirrors.kernel.org/linuxmint/stable/${MINT_VERSION}/linuxmint-${MINT_VERSION}-${MINT_EDITION}-${MINT_ARCH}.iso"
    log "URL: $MINT_ISO_URL"
    log "This is ~2.8GB and may take a while..."
    wget --progress=bar:force:noscroll -O "$MINT_ISO" "$MINT_ISO_URL" || {
        # Try alternate mirror
        warn "Primary mirror failed, trying secondary..."
        MINT_ISO_URL="https://mirror.csclub.uwaterloo.ca/linuxmint/stable/${MINT_VERSION}/linuxmint-${MINT_VERSION}-${MINT_EDITION}-${MINT_ARCH}.iso"
        wget --progress=bar:force:noscroll -O "$MINT_ISO" "$MINT_ISO_URL"
    }
fi
log "Base ISO ready."

# ---------------------------------------------------------------------------
# Step 3: Extract ISO
# ---------------------------------------------------------------------------
log "Step 3/6: Extracting ISO contents..."
mkdir -p "$EXTRACT_DIR"

MOUNT_POINT="${WORK_DIR}/mnt"
mkdir -p "$MOUNT_POINT"
mount -o loop,ro "$MINT_ISO" "$MOUNT_POINT"
rsync -a "$MOUNT_POINT/" "$EXTRACT_DIR/"
umount "$MOUNT_POINT"

log "Extracting squashfs filesystem (this takes a few minutes)..."
unsquashfs -f -d "$CHROOT_DIR" "$EXTRACT_DIR/casper/filesystem.squashfs"
log "Extraction complete."

# ---------------------------------------------------------------------------
# Step 4: Customize (chroot)
# ---------------------------------------------------------------------------
log "Step 4/6: Customizing NexusOS..."

# Mount for chroot
mount --bind /dev     "$CHROOT_DIR/dev"
mount --bind /run     "$CHROOT_DIR/run"
mount -t proc proc    "$CHROOT_DIR/proc"
mount -t sysfs sys    "$CHROOT_DIR/sys"
mount -t devpts devpts "$CHROOT_DIR/dev/pts"
cp /etc/resolv.conf "$CHROOT_DIR/etc/resolv.conf"

# Copy NexusOS files into chroot
mkdir -p "$CHROOT_DIR/opt/nexus"
cp -r "$SCRIPT_DIR/src"    "$CHROOT_DIR/opt/nexus/"
cp -r "$SCRIPT_DIR/config" "$CHROOT_DIR/opt/nexus/"

# Copy overlay files (systemd units, applets, desklets, motd, desktop files)
if [[ -d "$SCRIPT_DIR/overlay" ]]; then
    cp -r "$SCRIPT_DIR/overlay/"* "$CHROOT_DIR/" 2>/dev/null || true
fi

# Run customization inside chroot
chroot "$CHROOT_DIR" /bin/bash << 'CHROOT_EOF'
set -euo pipefail
export HOME=/root
export LC_ALL=C
export DEBIAN_FRONTEND=noninteractive

echo ">>> Updating packages..."
apt-get update -qq

echo ">>> Installing NexusOS dependencies..."
apt-get install -y -qq --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    sssd sssd-ad sssd-ldap realmd adcli krb5-user \
    samba-common-bin libnss-sss libpam-sss \
    sqlite3 curl jq \
    > /dev/null 2>&1

echo ">>> Setting up NexusOS Python environment..."
python3 -m venv /opt/nexus/venv
/opt/nexus/venv/bin/pip install --upgrade pip -q
/opt/nexus/venv/bin/pip install -q \
    pydantic click rich tomli \
    aiohttp aiofiles \
    ldap3 msal \
    sqlalchemy aiosqlite

echo ">>> Installing nexus-core and nexus-directory..."
/opt/nexus/venv/bin/pip install -q /opt/nexus/src/nexus-core
/opt/nexus/venv/bin/pip install -q /opt/nexus/src/nexus-directory

echo ">>> Creating nexus system user..."
useradd --system --home-dir /var/lib/nexus --shell /usr/sbin/nologin nexus 2>/dev/null || true
mkdir -p /var/lib/nexus /var/log/nexus /etc/nexus/certs /run/nexus
chown -R nexus:nexus /var/lib/nexus /var/log/nexus /run/nexus

echo ">>> Installing NexusOS configuration..."
cp /opt/nexus/config/nexus.conf /etc/nexus/nexus.conf
cp /opt/nexus/config/mcp-registry.json /etc/nexus/mcp-registry.json

echo ">>> Enabling NexusOS services..."
systemctl enable nexus-core.service  2>/dev/null || true
systemctl enable nexus-directory.service 2>/dev/null || true

echo ">>> Setting NexusOS branding..."
echo "NexusOS 0.1.0" > /etc/nexus-release

# Update lsb-release
if [[ -f /etc/lsb-release ]]; then
    sed -i 's/DISTRIB_ID=.*/DISTRIB_ID=NexusOS/' /etc/lsb-release
    sed -i 's/DISTRIB_DESCRIPTION=.*/DISTRIB_DESCRIPTION="NexusOS 0.1.0 (Cinnamon)"/' /etc/lsb-release
fi

# Update os-release
if [[ -f /etc/os-release ]]; then
    sed -i 's/^NAME=.*/NAME="NexusOS"/' /etc/os-release
    sed -i 's/^PRETTY_NAME=.*/PRETTY_NAME="NexusOS 0.1.0"/' /etc/os-release
    sed -i 's|^HOME_URL=.*|HOME_URL="https://nexus-os.dev"|' /etc/os-release
fi

# Install MOTD
if [[ -f /etc/nexus/motd ]]; then
    cp /etc/nexus/motd /etc/motd
fi

# Enable Cinnamon NexusOS applet in default panel
mkdir -p /usr/share/glib-2.0/schemas
cat > /usr/share/glib-2.0/schemas/90_nexus-os.gschema.override << 'SCHEMA_EOF'
[org.cinnamon]
enabled-applets=['panel1:left:0:menu@cinnamon.org','panel1:left:1:show-desktop@cinnamon.org','panel1:left:2:grouped-window-list@cinnamon.org','panel1:right:0:systray@cinnamon.org','panel1:right:1:xapp-status@cinnamon.org','panel1:right:2:notifications@cinnamon.org','panel1:right:3:printers@cinnamon.org','panel1:right:4:removable-drives@cinnamon.org','panel1:right:5:keyboard@cinnamon.org','panel1:right:6:favorites@cinnamon.org','panel1:right:7:network@cinnamon.org','panel1:right:8:sound@cinnamon.org','panel1:right:9:power@cinnamon.org','panel1:right:10:calendar@cinnamon.org','panel1:right:11:nexus-agents@nexus-os']
SCHEMA_EOF
glib-compile-schemas /usr/share/glib-2.0/schemas/ 2>/dev/null || true

echo ">>> Cleaning up..."
apt-get autoremove -y -qq > /dev/null 2>&1
apt-get clean
rm -rf /var/cache/apt/archives/*.deb /tmp/*

echo ">>> NexusOS chroot customization complete."
CHROOT_EOF

# Unmount chroot
umount "$CHROOT_DIR/dev/pts" 2>/dev/null || true
umount "$CHROOT_DIR/sys"     2>/dev/null || true
umount "$CHROOT_DIR/proc"    2>/dev/null || true
umount "$CHROOT_DIR/run"     2>/dev/null || true
umount "$CHROOT_DIR/dev"     2>/dev/null || true

log "Customization complete."

# ---------------------------------------------------------------------------
# Step 5: Rebuild ISO
# ---------------------------------------------------------------------------
log "Step 5/6: Rebuilding ISO (this takes several minutes)..."

# Repack squashfs
rm -f "$EXTRACT_DIR/casper/filesystem.squashfs"
mksquashfs "$CHROOT_DIR" "$EXTRACT_DIR/casper/filesystem.squashfs" \
    -comp xz -Xbcj x86 -b 1M -no-progress

# Update filesystem size
printf "$(du -sx --block-size=1 "$CHROOT_DIR" | cut -f1)" \
    > "$EXTRACT_DIR/casper/filesystem.size"

# Update checksums
cd "$EXTRACT_DIR"
rm -f md5sum.txt
find . -type f -not -name md5sum.txt -not -path './isolinux/*' \
    -exec md5sum {} \; > md5sum.txt

# Determine EFI boot path
EFI_IMG=""
if [[ -f "$EXTRACT_DIR/boot/grub/efi.img" ]]; then
    EFI_IMG="boot/grub/efi.img"
elif [[ -f "$EXTRACT_DIR/EFI/boot/efi.img" ]]; then
    EFI_IMG="EFI/boot/efi.img"
fi

# Build the ISO
mkdir -p "$OUT_DIR"
ISO_OUTPUT="${OUT_DIR}/nexus-os.iso"

if [[ -n "$EFI_IMG" ]]; then
    xorriso -as mkisofs \
        -iso-level 3 \
        -full-iso9660-filenames \
        -volid "NexusOS" \
        -output "$ISO_OUTPUT" \
        -eltorito-boot isolinux/isolinux.bin \
            -eltorito-catalog isolinux/boot.cat \
            -no-emul-boot \
            -boot-load-size 4 \
            -boot-info-table \
        -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
        -eltorito-alt-boot \
            -e "$EFI_IMG" \
            -no-emul-boot \
            -isohybrid-gpt-basdat \
        "$EXTRACT_DIR"
else
    xorriso -as mkisofs \
        -iso-level 3 \
        -full-iso9660-filenames \
        -volid "NexusOS" \
        -output "$ISO_OUTPUT" \
        -eltorito-boot isolinux/isolinux.bin \
            -eltorito-catalog isolinux/boot.cat \
            -no-emul-boot \
            -boot-load-size 4 \
            -boot-info-table \
        -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
        "$EXTRACT_DIR"
fi

log "ISO built."

# ---------------------------------------------------------------------------
# Step 6: Cleanup
# ---------------------------------------------------------------------------
log "Step 6/6: Cleanup..."
rm -rf "$CHROOT_DIR" "$EXTRACT_DIR" "${WORK_DIR}/mnt"
# Keep base ISO cached for faster rebuilds

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  NexusOS ISO build complete!                        ║${NC}"
echo -e "${CYAN}║                                                      ║${NC}"
echo -e "${CYAN}║  ISO: E:\\NexusOS\\out\\nexus-os.iso                   ║${NC}"
echo -e "${CYAN}║  Size: $(du -h "$ISO_OUTPUT" | cut -f1)                                         ║${NC}"
echo -e "${CYAN}║                                                      ║${NC}"
echo -e "${CYAN}║  To test in VMware Pro:                              ║${NC}"
echo -e "${CYAN}║  1. Create New VM → Linux → Ubuntu 64-bit            ║${NC}"
echo -e "${CYAN}║  2. Use ISO: E:\\NexusOS\\out\\nexus-os.iso             ║${NC}"
echo -e "${CYAN}║  3. RAM: 8GB+ | Disk: 40GB+ | CPUs: 4+              ║${NC}"
echo -e "${CYAN}║  4. Boot → Try or Install NexusOS                    ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
