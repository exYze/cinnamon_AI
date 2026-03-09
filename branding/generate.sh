#!/bin/bash
set -e

SRC_LOGO=/mnt/d/Downloads/logo.png
SRC_LOGO_WORDS=/mnt/d/Downloads/logo_w_words.png
BRAND=/mnt/e/NexusOS/branding

echo "=== Generating NexusOS branding assets ==="
echo "Source logo: $(identify -format '%wx%h' $SRC_LOGO)"
echo "Source logo+words: $(identify -format '%wx%h' $SRC_LOGO_WORDS)"

# Boot splash (640x480 for isolinux)
echo ">>> Boot splash..."
convert $SRC_LOGO_WORDS -resize 640x480 -gravity center -background '#0A0F1E' -extent 640x480 $BRAND/boot/splash.png

# GRUB splash (1920x1080) — fill width
echo ">>> GRUB splash..."
convert $SRC_LOGO_WORDS -resize 1920x -gravity center -background '#0A0F1E' -extent 1920x1080 $BRAND/boot/grub_splash.png

# Plymouth
echo ">>> Plymouth..."
convert $SRC_LOGO -resize 128x128 -gravity center -background none -extent 128x128 $BRAND/plymouth/logo.png
# Plymouth bg: logo fills ~40% of screen height
convert $SRC_LOGO -resize x450 -gravity center -background '#0A0F1E' -extent 1920x1080 $BRAND/plymouth/background.png

# Wallpapers (4K) — logo should be prominent
echo ">>> Wallpapers..."
# Default: icon-only logo, large and centered
convert $SRC_LOGO -resize x1200 -gravity center -background '#0A0F1E' -extent 3840x2160 $BRAND/wallpapers/nexus-default.png
# Dark variant: logo with text, fills most of the width
convert $SRC_LOGO_WORDS -resize 3000x -gravity center -background '#0A0F1E' -extent 3840x2160 $BRAND/wallpapers/nexus-dark.png

# Login screen — logo prominent
echo ">>> Login screen..."
convert $SRC_LOGO -resize x700 -gravity center -background '#0A0F1E' -extent 1920x1080 $BRAND/login/background.png
convert $SRC_LOGO -resize 128x128 -gravity center -background none -extent 128x128 $BRAND/login/logo.png

# Cinnamon
echo ">>> Cinnamon..."
convert $SRC_LOGO -resize 24x24 $BRAND/cinnamon/menu-icon.png
convert $SRC_LOGO -resize 96x96 $BRAND/cinnamon/about-logo.png
convert $SRC_LOGO -resize 48x48 $BRAND/cinnamon/distributor-logo.png

# System icons (all sizes)
echo ">>> Icons..."
for size in 16 24 32 48 64 128 256; do
    convert $SRC_LOGO -resize ${size}x${size} -gravity center -background none -extent ${size}x${size} $BRAND/icons/nexus-os-${size}.png
done

# Installer
echo ">>> Installer..."
convert $SRC_LOGO -resize 96x96 $BRAND/installer/logo.png
convert $SRC_LOGO_WORDS -resize 200x -gravity center -background '#0A0F1E' -extent 200x600 $BRAND/installer/sidebar.png

echo ""
echo "=== All branding assets generated ==="
