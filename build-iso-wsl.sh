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
# resolv.conf is often a symlink in Ubuntu/Mint — remove it first, then copy
rm -f "$CHROOT_DIR/etc/resolv.conf"
cp /etc/resolv.conf "$CHROOT_DIR/etc/resolv.conf" 2>/dev/null || echo "nameserver 8.8.8.8" > "$CHROOT_DIR/etc/resolv.conf"

# Copy NexusOS files into chroot
mkdir -p "$CHROOT_DIR/opt/nexus"
cp -r "$SCRIPT_DIR/src"    "$CHROOT_DIR/opt/nexus/"
cp -r "$SCRIPT_DIR/config" "$CHROOT_DIR/opt/nexus/"

# Copy overlay files (systemd units, applets, desklets, motd, desktop files)
if [[ -d "$SCRIPT_DIR/overlay" ]]; then
    cp -r "$SCRIPT_DIR/overlay/"* "$CHROOT_DIR/" 2>/dev/null || true
fi

# Pre-copy branding assets into chroot (needed by chroot branding steps)
if [[ -d "$SCRIPT_DIR/branding" ]]; then
    mkdir -p "$CHROOT_DIR/usr/share/nexus-os/branding"
    mkdir -p "$CHROOT_DIR/usr/share/backgrounds/nexus-os"
    # Copy menu icon
    for f in "$SCRIPT_DIR/branding/cinnamon/"*; do
        [[ -f "$f" ]] && cp "$f" "$CHROOT_DIR/usr/share/nexus-os/branding/"
    done
    # Copy wallpapers
    for f in "$SCRIPT_DIR/branding/wallpapers/"*.{png,jpg,jpeg} ; do
        [[ -f "$f" ]] && cp "$f" "$CHROOT_DIR/usr/share/backgrounds/nexus-os/"
    done
    # Copy login assets
    for f in "$SCRIPT_DIR/branding/login/"*; do
        [[ -f "$f" ]] && cp "$f" "$CHROOT_DIR/usr/share/nexus-os/branding/"
    done
    # Copy plymouth assets
    for f in "$SCRIPT_DIR/branding/plymouth/"*.png; do
        [[ -f "$f" ]] && cp "$f" "$CHROOT_DIR/usr/share/nexus-os/branding/"
    done

    # Determine which wallpaper file to use as default
    if [[ -f "$CHROOT_DIR/usr/share/backgrounds/nexus-os/nexus-default.jpg" ]]; then
        NEXUS_WALLPAPER_FILE="nexus-default.jpg"
    else
        NEXUS_WALLPAPER_FILE="nexus-default.png"
    fi
    log "Default wallpaper: $NEXUS_WALLPAPER_FILE"
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
    python3-gi gir1.2-gtk-3.0 \
    sssd sssd-ad sssd-ldap realmd adcli krb5-user \
    samba-common-bin libnss-sss libpam-sss \
    sqlite3 curl jq imagemagick \
    > /dev/null 2>&1

echo ">>> Setting up NexusOS Python environment..."
python3 -m venv --system-site-packages /opt/nexus/venv
/opt/nexus/venv/bin/pip install --upgrade pip -q
/opt/nexus/venv/bin/pip install -q \
    pydantic click rich tomli \
    aiohttp aiofiles \
    ldap3 msal bcrypt \
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

# --- Replace default wallpaper ---
# Mint stores wallpapers in /usr/share/backgrounds/linuxmint/
# The default is set via gschema, dconf, linuxmint adjustments, AND pre-baked user dconf
echo ">>> Replacing wallpapers (aggressive)..."
NEXUS_WALL_DIR=/usr/share/backgrounds/nexus-os

# Determine our wallpaper file
if [[ -f "$NEXUS_WALL_DIR/nexus-default.jpg" ]]; then
    NEXUS_WALL="$NEXUS_WALL_DIR/nexus-default.jpg"
elif [[ -f "$NEXUS_WALL_DIR/nexus-default.png" ]]; then
    NEXUS_WALL="$NEXUS_WALL_DIR/nexus-default.png"
fi

# Replace ALL Mint default wallpapers with NexusOS ones
if [[ -d /usr/share/backgrounds/linuxmint ]]; then
    for mintwall in /usr/share/backgrounds/linuxmint/*.png /usr/share/backgrounds/linuxmint/*.jpg; do
        [[ -f "$mintwall" ]] && cp "$NEXUS_WALL" "$mintwall"
    done
fi

# Replace default_background symlink/file
for default_bg in /usr/share/backgrounds/default_background.jpg /usr/share/backgrounds/default_background.png; do
    rm -f "$default_bg"
    cp "$NEXUS_WALL" "$default_bg" 2>/dev/null || true
done

# Also drop our wallpaper as the exact filenames Mint uses
cp "$NEXUS_WALL" /usr/share/backgrounds/linuxmint-tessa.jpg 2>/dev/null || true
cp "$NEXUS_WALL" /usr/share/backgrounds/linuxmint-wilma.jpg 2>/dev/null || true
cp "$NEXUS_WALL" /usr/share/backgrounds/linuxmint/default_background.jpg 2>/dev/null || true

# Replace via linuxmint adjustments (this is what live session uses)
if [[ -d /etc/linuxmint/adjustments ]]; then
    find /etc/linuxmint/adjustments -name '*.overrides' -exec \
        sed -i "s|picture-uri=.*|picture-uri='file://${NEXUS_WALL}'|g" {} \;
fi

# Replace ALL background images in backgrounds dir to catch anything we missed
for bgimg in /usr/share/backgrounds/*.jpg /usr/share/backgrounds/*.png; do
    if [[ -f "$bgimg" ]] && [[ "$bgimg" != "$NEXUS_WALL_DIR/"* ]]; then
        cp "$NEXUS_WALL" "$bgimg" 2>/dev/null || true
    fi
done

# --- Generate and install NexusOS menu icon ---
echo ">>> Creating NexusOS menu icon from wallpaper..."
NEXUS_ICON_DIR=/usr/share/icons/hicolor
NEXUS_WALL_SRC="$NEXUS_WALL"
NEXUS_MENU_ICON=/usr/share/nexus-os/branding/nexus-menu.png

# Generate a clean square icon from the center of our wallpaper (the N logo)
# Crop center square, then resize to multiple icon sizes
if command -v convert >/dev/null 2>&1 && [[ -f "$NEXUS_WALL_SRC" ]]; then
    # Extract center square (the logo area) from wallpaper
    convert "$NEXUS_WALL_SRC" -gravity center -crop 50%x90%+0+0 +repage \
        -resize 256x256 "$NEXUS_MENU_ICON"

    # Generate all standard icon sizes
    for size in 16 22 24 32 48 64 96 128 256; do
        mkdir -p "$NEXUS_ICON_DIR/${size}x${size}/apps"
        convert "$NEXUS_MENU_ICON" -resize ${size}x${size} \
            "$NEXUS_ICON_DIR/${size}x${size}/apps/nexus-os-logo.png"
        # Also install as linuxmint-logo so menu applet finds it
        cp "$NEXUS_ICON_DIR/${size}x${size}/apps/nexus-os-logo.png" \
            "$NEXUS_ICON_DIR/${size}x${size}/apps/linuxmint-logo-ring-symbolic.png" 2>/dev/null || true
        cp "$NEXUS_ICON_DIR/${size}x${size}/apps/nexus-os-logo.png" \
            "$NEXUS_ICON_DIR/${size}x${size}/apps/linuxmint-logo.png" 2>/dev/null || true
    done
    echo "  Generated NexusOS icons in all sizes"
else
    echo "  WARN: ImageMagick not available, using branding asset as-is"
    NEXUS_MENU_ICON=/usr/share/nexus-os/branding/menu-icon.png
fi

# Replace linuxmint-logo icons in ALL icon themes (Mint-Y, Mint-X, etc)
echo ">>> Replacing Mint logo in all icon themes..."
find /usr/share/icons -name 'linuxmint-logo*' -type f 2>/dev/null | while read -r iconfile; do
    # Use the 48px icon as a safe default replacement for all sizes
    cp "$NEXUS_ICON_DIR/48x48/apps/nexus-os-logo.png" "$iconfile" 2>/dev/null || true
done || true

# Replace cinnamon theme menu icon
cp "$NEXUS_MENU_ICON" /usr/share/cinnamon/theme/menu-symbolic.svg 2>/dev/null || true

# Update icon caches
gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
for theme_dir in /usr/share/icons/Mint-*/; do
    gtk-update-icon-cache "$theme_dir" 2>/dev/null || true
done

# --- Configure Cinnamon menu applet to use our icon ---
echo ">>> Configuring menu applet icon..."
# Write menu applet config for the live session mint user
MINT_MENU_DIR="/home/mint/.cinnamon/configs/menu@cinnamon.org"
mkdir -p "$MINT_MENU_DIR"
# Find existing config or create one — the applet ID is typically 0
cat > "$MINT_MENU_DIR/0.json" << 'MENU_CFG_EOF'
{
    "layout": {"type": "layout", "pages": ["page_0"], "page_0": {"type": "page", "title": "Settings", "sections": ["section_0"]}},
    "menu-custom": {"type": "switch", "default": true, "value": true},
    "menu-icon": {"type": "iconfilechooser", "default": "linuxmint-logo-ring-symbolic", "value": "/usr/share/icons/hicolor/48x48/apps/nexus-os-logo.png"},
    "menu-icon-size": {"type": "spinbutton", "default": 32, "value": 32},
    "menu-label": {"type": "entry", "default": "", "value": ""}
}
MENU_CFG_EOF
chown -R 1000:1000 /home/mint/.cinnamon 2>/dev/null || true

# --- Determine wallpaper filename for configs ---
if [[ -f "$NEXUS_WALL_DIR/nexus-default.jpg" ]]; then
    WALL_FILENAME="nexus-default.jpg"
else
    WALL_FILENAME="nexus-default.png"
fi
WALL_URI="file:///usr/share/backgrounds/nexus-os/${WALL_FILENAME}"

# --- Cinnamon gschema overrides (wallpaper + applet + menu icon) ---
echo ">>> Setting Cinnamon defaults..."
mkdir -p /usr/share/glib-2.0/schemas
cat > /usr/share/glib-2.0/schemas/90_nexus-os.gschema.override << SCHEMA_EOF
[org.cinnamon]
enabled-applets=['panel1:left:0:menu@cinnamon.org','panel1:left:1:show-desktop@cinnamon.org','panel1:left:2:grouped-window-list@cinnamon.org','panel1:right:0:systray@cinnamon.org','panel1:right:1:xapp-status@cinnamon.org','panel1:right:2:notifications@cinnamon.org','panel1:right:3:printers@cinnamon.org','panel1:right:4:removable-drives@cinnamon.org','panel1:right:5:keyboard@cinnamon.org','panel1:right:6:favorites@cinnamon.org','panel1:right:7:network@cinnamon.org','panel1:right:8:sound@cinnamon.org','panel1:right:9:power@cinnamon.org','panel1:right:10:calendar@cinnamon.org','panel1:right:11:nexus-agents@nexus-os']

[org.cinnamon.desktop.background]
picture-uri='${WALL_URI}'
picture-options='zoom'

[org.cinnamon.theme]
name='Mint-Y-Dark'
SCHEMA_EOF
glib-compile-schemas /usr/share/glib-2.0/schemas/ 2>/dev/null || true

# --- Fix for live session (mint user) ---
# The live session runs as user "mint" who has dconf defaults baked in.
# We add a system-db that provides our wallpaper as default.
# IMPORTANT: Do NOT delete the mint user's dconf database — it contains
# all Cinnamon settings (panels, themes, etc). Deleting it breaks the desktop.
mkdir -p /etc/dconf/profile
cat > /etc/dconf/profile/user << 'DCONF_EOF'
user-db:user
system-db:nexus
DCONF_EOF

mkdir -p /etc/dconf/db/nexus.d
cat > /etc/dconf/db/nexus.d/00-nexus-branding << DCONF_BRAND_EOF
[org/cinnamon/desktop/background]
picture-uri='${WALL_URI}'
picture-options='zoom'
DCONF_BRAND_EOF

dconf update 2>/dev/null || true

# --- Patch the mint user's dconf to set wallpaper without nuking it ---
# Use python3 + gi to write ONLY the wallpaper key into the user db
if [[ -d /home/mint ]]; then
    echo ">>> Patching mint user wallpaper setting..."
    # Create an autostart that sets wallpaper + desktop icons on first login
    mkdir -p /etc/xdg/autostart
    cat > /etc/xdg/autostart/nexus-branding.desktop << AUTOSTART_EOF
[Desktop Entry]
Type=Application
Name=NexusOS Branding
Exec=/bin/bash -c "gsettings set org.cinnamon.desktop.background picture-uri '${WALL_URI}' && gsettings set org.cinnamon.desktop.background picture-options 'zoom' && gsettings set org.nemo.desktop show-desktop-icons true"
X-GNOME-Autostart-Phase=Applications
NoDisplay=true
AUTOSTART_EOF
fi

# --- Also replace the ACTUAL image files that the mint dconf points to ---
# This is the nuclear option: whatever path the dconf has, the image IS ours
echo ">>> Overwriting all system background images with NexusOS wallpaper..."
# Find the exact filename the mint dconf is pointing to and replace it
for bg_dir in /usr/share/backgrounds /usr/share/backgrounds/linuxmint; do
    if [[ -d "$bg_dir" ]]; then
        find "$bg_dir" -maxdepth 1 -type f \( -name "*.jpg" -o -name "*.png" \) | while read bgfile; do
            cp "$NEXUS_WALL" "$bgfile"
        done
    fi
done

# --- Replace Plymouth boot animation (must happen inside chroot for theme switch) ---
echo ">>> Replacing Plymouth boot theme..."

# Generate a small NexusOS logo icon (128x128) for Plymouth spinner overlay
NEXUS_SMALL_LOGO=/tmp/nexus-plymouth-logo.png
if command -v convert >/dev/null 2>&1 && [[ -f /usr/share/backgrounds/nexus-os/nexus-default.png ]]; then
    convert /usr/share/backgrounds/nexus-os/nexus-default.png \
        -gravity center -crop 50%x90%+0+0 +repage \
        -resize 128x128 "$NEXUS_SMALL_LOGO"
else
    # Fallback: use branding logo if available
    cp /usr/share/nexus-os/branding/logo.png "$NEXUS_SMALL_LOGO" 2>/dev/null || true
fi

# Replace ALL PNGs in Plymouth themes — the LM spinner icon could be named anything
for theme_dir in /usr/share/plymouth/themes/mint-logo /usr/share/plymouth/themes/ubuntu-logo /usr/share/plymouth/themes/spinner; do
    if [[ -d "$theme_dir" ]]; then
        echo "  Patching Plymouth theme: $theme_dir"
        for imgfile in "$theme_dir"/*.png; do
            [[ -f "$imgfile" ]] || continue
            fname=$(basename "$imgfile")
            # For background/large images, use our wallpaper
            # For logo/icon/watermark images, use our small logo
            case "$fname" in
                *background*|*bg*)
                    cp /usr/share/backgrounds/nexus-os/nexus-default.png "$imgfile" 2>/dev/null || true
                    ;;
                *)
                    # Replace ALL other PNGs (logos, spinners, watermarks) with our logo
                    cp "$NEXUS_SMALL_LOGO" "$imgfile" 2>/dev/null || true
                    ;;
            esac
        done
    fi
done

# Also search for the LM logo in ALL plymouth themes
find /usr/share/plymouth -name "*.png" -type f 2>/dev/null | while read -r pimg; do
    fname=$(basename "$pimg")
    case "$fname" in
        *mint*|*logo*|*watermark*|*bgrt*)
            cp "$NEXUS_SMALL_LOGO" "$pimg" 2>/dev/null || true
            ;;
    esac
done || true

# Set up our custom Plymouth theme with proper script
if [[ -f "$NEXUS_SMALL_LOGO" ]]; then
    NEXUS_PLYMOUTH=/usr/share/plymouth/themes/nexus-os
    mkdir -p "$NEXUS_PLYMOUTH"
    cp "$NEXUS_SMALL_LOGO" "$NEXUS_PLYMOUTH/logo.png"
    # Pre-scale the background to 1920x1080 for fast Plymouth rendering
    # Plymouth framebuffer is limited; a 6MB PNG is too heavy
    if command -v convert >/dev/null 2>&1; then
        convert /usr/share/backgrounds/nexus-os/nexus-default.png \
            -resize 1920x1080! "$NEXUS_PLYMOUTH/background.png"
    else
        cp /usr/share/backgrounds/nexus-os/nexus-default.png "$NEXUS_PLYMOUTH/background.png" 2>/dev/null || true
    fi

    cat > "$NEXUS_PLYMOUTH/nexus-os.plymouth" << 'PLY_EOF'
[Plymouth Theme]
Name=NexusOS
Description=NexusOS Boot Screen
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/nexus-os
ScriptFile=/usr/share/plymouth/themes/nexus-os/nexus-os.script
PLY_EOF

    cat > "$NEXUS_PLYMOUTH/nexus-os.script" << 'PLYSCRIPT_EOF'
# NexusOS Plymouth — full-screen wallpaper only (logo is already in the image)
bg = Image("background.png");
scaled_bg = bg.Scale(Window.GetWidth(), Window.GetHeight());
bg_sprite = Sprite(scaled_bg);
bg_sprite.SetPosition(0, 0, -100);

progress = 0;
fun refresh_callback() {
    progress++;
}
Plymouth.SetRefreshFunction(refresh_callback);
PLYSCRIPT_EOF

    # Set as default theme
    plymouth-set-default-theme nexus-os 2>/dev/null || true
    update-alternatives --install /usr/share/plymouth/themes/default.plymouth \
        default.plymouth "$NEXUS_PLYMOUTH/nexus-os.plymouth" 200 2>/dev/null || true
    update-initramfs -u 2>/dev/null || true
fi

rm -f "$NEXUS_SMALL_LOGO"

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
# Step 4b: Bootloader branding (outside chroot — these are ISO-level files)
# ---------------------------------------------------------------------------
log "Applying branding assets..."

BRAND_DIR="${SCRIPT_DIR}/branding"

# --- Boot menu splash ---
if [[ -f "$BRAND_DIR/boot/splash.png" ]]; then
    cp "$BRAND_DIR/boot/splash.png" "$EXTRACT_DIR/isolinux/splash.png"
    log "  Applied: boot splash (isolinux)"
fi
if [[ -f "$BRAND_DIR/boot/grub_splash.png" ]]; then
    cp "$BRAND_DIR/boot/grub_splash.png" "$EXTRACT_DIR/boot/grub/splash.png"
    log "  Applied: boot splash (GRUB)"
fi

# --- Plymouth boot animation ---
if [[ -d "$BRAND_DIR/plymouth" ]]; then
    PLYMOUTH_DIR="$CHROOT_DIR/usr/share/plymouth/themes/nexus-os"
    mkdir -p "$PLYMOUTH_DIR"

    # Copy all plymouth assets
    for f in "$BRAND_DIR/plymouth/"*; do
        [[ -f "$f" ]] && cp "$f" "$PLYMOUTH_DIR/"
    done

    # Create plymouth theme descriptor
    cat > "$PLYMOUTH_DIR/nexus-os.plymouth" << 'PLYMOUTH_EOF'
[Plymouth Theme]
Name=NexusOS
Description=NexusOS Autonomous AI Boot Screen
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/nexus-os
ScriptFile=/usr/share/plymouth/themes/nexus-os/nexus-os.script
PLYMOUTH_EOF

    # Create plymouth animation script
    cat > "$PLYMOUTH_DIR/nexus-os.script" << 'PLYSCRIPT_EOF'
# NexusOS Plymouth Boot Script
background = Image("background.png");
logo = Image("logo.png");

bg_sprite = Sprite(background.Scale(Window.GetWidth(), Window.GetHeight()));
bg_sprite.SetPosition(0, 0, -100);

logo_sprite = Sprite(logo);
logo_sprite.SetPosition(
    Window.GetWidth() / 2 - logo.GetWidth() / 2,
    Window.GetHeight() / 2 - logo.GetHeight() / 2,
    10
);

# Pulsing opacity animation
progress = 0;
fun refresh_callback() {
    progress++;
    opacity = Math.Abs(Math.Sin(progress * 0.03)) * 0.5 + 0.5;
    logo_sprite.SetOpacity(opacity);
}
Plymouth.SetRefreshFunction(refresh_callback);
PLYSCRIPT_EOF

    # Set as default theme in chroot
    chroot "$CHROOT_DIR" /bin/bash -c "
        plymouth-set-default-theme nexus-os 2>/dev/null || true
        update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth /usr/share/plymouth/themes/nexus-os/nexus-os.plymouth 200 2>/dev/null || true
    " 2>/dev/null || true

    log "  Applied: Plymouth boot animation"
fi

# --- Desktop wallpapers ---
if [[ -d "$BRAND_DIR/wallpapers" ]]; then
    WALL_DIR="$CHROOT_DIR/usr/share/backgrounds/nexus-os"
    mkdir -p "$WALL_DIR"

    for f in "$BRAND_DIR/wallpapers/"*.{png,jpg,jpeg}; do
        [[ -f "$f" ]] && cp "$f" "$WALL_DIR/"
    done

    # Schemas were already written inside chroot, just recompile
    chroot "$CHROOT_DIR" glib-compile-schemas /usr/share/glib-2.0/schemas/ 2>/dev/null || true

    log "  Applied: Desktop wallpapers"
fi

# --- Login screen ---
if [[ -d "$BRAND_DIR/login" ]]; then
    GREETER_CONF="$CHROOT_DIR/etc/lightdm/slick-greeter.conf"
    mkdir -p "$CHROOT_DIR/etc/lightdm"
    mkdir -p "$CHROOT_DIR/usr/share/nexus-os/branding"

    for f in "$BRAND_DIR/login/"*; do
        [[ -f "$f" ]] && cp "$f" "$CHROOT_DIR/usr/share/nexus-os/branding/"
    done

    cat > "$GREETER_CONF" << 'GREETER_EOF'
[Greeter]
background=/usr/share/nexus-os/branding/background.png
logo=/usr/share/nexus-os/branding/logo.png
draw-grid=false
theme-name=Mint-Y-Dark
icon-theme-name=Mint-Y-Dark
GREETER_EOF

    log "  Applied: Login screen branding"
fi

# --- Cinnamon menu icon and about logo ---
if [[ -d "$BRAND_DIR/cinnamon" ]]; then
    # Menu icon (replaces Mint logo in panel start button)
    if [[ -f "$BRAND_DIR/cinnamon/menu-icon.svg" ]]; then
        cp "$BRAND_DIR/cinnamon/menu-icon.svg" \
            "$CHROOT_DIR/usr/share/cinnamon/theme/menu-symbolic.svg" 2>/dev/null || true
        # Also place in common icon locations
        mkdir -p "$CHROOT_DIR/usr/share/icons/hicolor/scalable/apps"
        cp "$BRAND_DIR/cinnamon/menu-icon.svg" \
            "$CHROOT_DIR/usr/share/icons/hicolor/scalable/apps/nexus-os-menu.svg"
    fi

    # About dialog logo
    if [[ -f "$BRAND_DIR/cinnamon/about-logo.png" ]]; then
        cp "$BRAND_DIR/cinnamon/about-logo.png" \
            "$CHROOT_DIR/usr/share/cinnamon/theme/about-logo.png" 2>/dev/null || true
    fi

    # Distributor logo (used by system info panels)
    if [[ -f "$BRAND_DIR/cinnamon/distributor-logo.png" ]]; then
        mkdir -p "$CHROOT_DIR/usr/share/icons/hicolor/48x48/apps"
        cp "$BRAND_DIR/cinnamon/distributor-logo.png" \
            "$CHROOT_DIR/usr/share/icons/hicolor/48x48/apps/distributor-logo.png"
    fi

    log "  Applied: Cinnamon branding"
fi

# --- System icons ---
if [[ -d "$BRAND_DIR/icons" ]]; then
    ICON_BASE="$CHROOT_DIR/usr/share/icons/hicolor"

    # Install sized PNGs
    for size in 16 24 32 48 64 128 256; do
        if [[ -f "$BRAND_DIR/icons/nexus-os-${size}.png" ]]; then
            mkdir -p "$ICON_BASE/${size}x${size}/apps"
            cp "$BRAND_DIR/icons/nexus-os-${size}.png" \
                "$ICON_BASE/${size}x${size}/apps/nexus-os.png"
        fi
    done

    # Install scalable SVGs
    if [[ -f "$BRAND_DIR/icons/nexus-os.svg" ]]; then
        mkdir -p "$ICON_BASE/scalable/apps"
        cp "$BRAND_DIR/icons/nexus-os.svg" "$ICON_BASE/scalable/apps/nexus-os.svg"
    fi

    # Agent symbolic icon (for panel applet)
    if [[ -f "$BRAND_DIR/icons/nexus-agent-symbolic.svg" ]]; then
        mkdir -p "$ICON_BASE/scalable/status"
        cp "$BRAND_DIR/icons/nexus-agent-symbolic.svg" \
            "$ICON_BASE/scalable/status/nexus-agent-symbolic.svg"
    fi

    # Update icon cache
    chroot "$CHROOT_DIR" gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true

    log "  Applied: System icons"
fi

# --- Installer branding ---
if [[ -d "$BRAND_DIR/installer" ]]; then
    INST_DIR="$CHROOT_DIR/usr/share/ubiquity/pixmaps"
    mkdir -p "$INST_DIR" 2>/dev/null || true

    if [[ -f "$BRAND_DIR/installer/logo.png" ]]; then
        cp "$BRAND_DIR/installer/logo.png" "$INST_DIR/nexus-os-logo.png"
    fi
    if [[ -f "$BRAND_DIR/installer/sidebar.png" ]]; then
        cp "$BRAND_DIR/installer/sidebar.png" "$INST_DIR/nexus-os-sidebar.png"
    fi

    log "  Applied: Installer branding"
fi

log "Applying bootloader branding..."

# Rebrand isolinux (BIOS boot menu)
if [[ -f "$EXTRACT_DIR/isolinux/isolinux.cfg" ]]; then
    sed -i 's/Linux Mint/NexusOS/g' "$EXTRACT_DIR/isolinux/isolinux.cfg"
    sed -i 's/Start Linux Mint/Start NexusOS/g' "$EXTRACT_DIR/isolinux/isolinux.cfg"
    sed -i 's/linuxmint/nexus-os/g' "$EXTRACT_DIR/isolinux/isolinux.cfg"
fi

# Rebrand any .cfg files in isolinux/
for cfg in "$EXTRACT_DIR"/isolinux/*.cfg; do
    if [[ -f "$cfg" ]]; then
        sed -i 's/Linux Mint/NexusOS/g' "$cfg"
        sed -i 's/Start Linux Mint/Start NexusOS/g' "$cfg"
    fi
done

# Rebrand GRUB (UEFI boot menu)
if [[ -f "$EXTRACT_DIR/boot/grub/grub.cfg" ]]; then
    sed -i 's/Linux Mint/NexusOS/g' "$EXTRACT_DIR/boot/grub/grub.cfg"
    sed -i 's/Start Linux Mint/Start NexusOS/g' "$EXTRACT_DIR/boot/grub/grub.cfg"
    sed -i 's/linuxmint/nexus-os/g' "$EXTRACT_DIR/boot/grub/grub.cfg"
    # Set framebuffer resolution for proper Plymouth display
    if ! grep -q 'GRUB_GFXMODE' "$EXTRACT_DIR/boot/grub/grub.cfg"; then
        sed -i '1i set gfxmode=1920x1080,1280x1024,auto' "$EXTRACT_DIR/boot/grub/grub.cfg"
        sed -i '2i set gfxpayload=keep' "$EXTRACT_DIR/boot/grub/grub.cfg"
    fi
fi

# Also set in chroot's default grub config for installed systems
if [[ -f "$CHROOT_DIR/etc/default/grub" ]]; then
    sed -i 's/^#\?GRUB_GFXMODE=.*/GRUB_GFXMODE=1920x1080,1280x1024,auto/' "$CHROOT_DIR/etc/default/grub"
    if ! grep -q 'GRUB_GFXPAYLOAD_LINUX' "$CHROOT_DIR/etc/default/grub"; then
        echo 'GRUB_GFXPAYLOAD_LINUX=keep' >> "$CHROOT_DIR/etc/default/grub"
    fi
fi

# Rebrand GRUB loopback config
if [[ -f "$EXTRACT_DIR/boot/grub/loopback.cfg" ]]; then
    sed -i 's/Linux Mint/NexusOS/g' "$EXTRACT_DIR/boot/grub/loopback.cfg"
fi

# Rebrand the .disk info file
if [[ -f "$EXTRACT_DIR/.disk/info" ]]; then
    echo 'NexusOS 0.1.0 "Autonomous" - Release amd64' > "$EXTRACT_DIR/.disk/info"
fi

# Replace the isolinux splash text (txt.cfg usually contains menu labels)
for cfg in "$EXTRACT_DIR"/isolinux/txt.cfg "$EXTRACT_DIR"/isolinux/menu.cfg; do
    if [[ -f "$cfg" ]]; then
        sed -i 's/Linux Mint [0-9]* [0-9]*-bit/NexusOS 0.1.0/g' "$cfg"
        sed -i 's/Linux Mint/NexusOS/g' "$cfg"
        sed -i 's/Welcome to .*/Welcome to NexusOS 0.1.0/g' "$cfg"
    fi
done

log "Bootloader branding applied."

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
