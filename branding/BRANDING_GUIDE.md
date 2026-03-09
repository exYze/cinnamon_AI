# NexusOS Branding Guide

Place your custom assets in the directories below. The build script will
automatically apply them to the ISO, replacing all Linux Mint branding.

---

## 1. Boot Menu Splash (`branding/boot/`)

The first thing users see when the ISO boots.

| File | Size | Format | Notes |
|------|------|--------|-------|
| `splash.png` | 640x480 | PNG (indexed color, max 16 colors) | BIOS boot menu background (isolinux) |
| `grub_splash.png` | 1920x1080 | PNG | UEFI/GRUB boot menu background |

**Design tip**: Dark background with NexusOS logo centered top, menu items appear in the lower half.

---

## 2. Plymouth Boot Animation (`branding/plymouth/`)

The animation shown during OS startup (after bootloader, before login).

| File | Size | Format | Notes |
|------|------|--------|-------|
| `logo.png` | 128x128 | PNG (transparent bg) | Main logo shown during boot |
| `logo_16bit.png` | 128x128 | PNG (16-bit) | Fallback for older hardware |
| `bullet.png` | 16x16 | PNG (transparent bg) | Progress dot (active) |
| `lock.png` | 32x32 | PNG (transparent bg) | Shown when screen is locked |
| `background.png` | 1920x1080 | PNG | Boot splash background |
| `animation_*.png` | 128x128 | PNG sequence | Optional: animated frames (001-024) |

**Theme colors** are defined in the build script. Default: dark navy (#0A0F1E) background with cyan (#00B4FF) accents.

---

## 3. Desktop Wallpapers (`branding/wallpapers/`)

| File | Size | Format | Notes |
|------|------|--------|-------|
| `nexus-default.png` | 3840x2160 | PNG or JPG | Default wallpaper (4K) |
| `nexus-dark.png` | 3840x2160 | PNG or JPG | Dark variant |
| `nexus-light.png` | 3840x2160 | PNG or JPG | Light variant (optional) |
| `nexus-abstract.png` | 3840x2160 | PNG or JPG | Extra option (optional) |

**Design tip**: Subtle, professional. Think dark gradients with geometric patterns or circuit-board aesthetics. The NexusOS logo watermark in the corner is a nice touch.

---

## 4. Login Screen (`branding/login/`)

Used by Slick Greeter (LightDM), the login screen manager.

| File | Size | Format | Notes |
|------|------|--------|-------|
| `background.png` | 1920x1080 | PNG or JPG | Login screen background |
| `logo.png` | 128x128 | PNG (transparent bg) | Logo above the login prompt |
| `badge.png` | 64x64 | PNG (transparent bg) | Session badge icon |

---

## 5. Cinnamon Desktop (`branding/cinnamon/`)

Panel, menu, and system UI branding.

| File | Size | Format | Notes |
|------|------|--------|-------|
| `menu-icon.svg` | 24x24 | SVG | Start menu button icon (replaces Mint logo in panel) |
| `menu-icon.png` | 24x24 | PNG (transparent bg) | Fallback if SVG not supported |
| `about-logo.png` | 96x96 | PNG (transparent bg) | Shown in "About This Computer" dialog |
| `distributor-logo.png` | 48x48 | PNG (transparent bg) | System tray / info panels |
| `panel-banner.svg` | 200x28 | SVG | Optional: text banner for panel |

---

## 6. System Icons (`branding/icons/`)

Application and system icons.

| File | Size | Format | Notes |
|------|------|--------|-------|
| `nexus-os.svg` | scalable | SVG | Main app icon (scalable) |
| `nexus-os-16.png` | 16x16 | PNG | Favicon / small icon |
| `nexus-os-24.png` | 24x24 | PNG | Panel / toolbar |
| `nexus-os-32.png` | 32x32 | PNG | Menu items |
| `nexus-os-48.png` | 48x48 | PNG | App grid |
| `nexus-os-64.png` | 64x64 | PNG | Large icons |
| `nexus-os-128.png` | 128x128 | PNG | About dialogs |
| `nexus-os-256.png` | 256x256 | PNG | High-DPI |
| `nexus-agent-symbolic.svg` | 16x16 | SVG | Agent applet panel icon (symbolic/monochrome) |

---

## 7. Installer (`branding/installer/`)

Shown during the OS installation process.

| File | Size | Format | Notes |
|------|------|--------|-------|
| `logo.png` | 96x96 | PNG (transparent bg) | Installer header logo |
| `sidebar.png` | 200x600 | PNG | Installer sidebar graphic |

---

## Quick Start with AI Image Generation

If you want to generate these assets quickly, use this prompt template with
an image generation tool (Midjourney, DALL-E, Flux, etc.):

### Logo prompt:
```
Minimalist tech logo for "NexusOS", an autonomous AI operating system.
Clean geometric design, interconnected nodes forming an "N" shape.
Colors: cyan (#00B4FF) on dark navy (#0A0F1E). No text. Transparent background.
Flat design, suitable for 16px to 256px scaling.
```

### Wallpaper prompt:
```
Dark abstract desktop wallpaper, 4K resolution. Deep navy blue (#0A0F1E)
to dark blue (#1E2A3A) gradient. Subtle geometric grid pattern with
glowing cyan (#00B4FF) node connections. Futuristic, minimal, professional.
No text or logos.
```

### Boot splash prompt:
```
Dark boot screen background, 640x480. Near-black (#0A0F1E) with subtle
radial gradient. Small NexusOS logo centered in top third. Understated,
clean. No text needed (menu text is overlaid by bootloader).
```

---

## Color Palette

| Name | Hex | Usage |
|------|-----|-------|
| Background Dark | `#0A0F1E` | Primary background |
| Background Mid | `#141E32` | Cards, panels, elevated surfaces |
| Accent Cyan | `#00B4FF` | Primary accent, active states, links |
| Accent Green | `#00DC82` | Success, running agents |
| Accent Yellow | `#FFC832` | Warnings, paused states |
| Accent Red | `#FF5050` | Errors, terminated |
| Text Primary | `#DCE6FF` | Main text |
| Text Secondary | `#8CA0C8` | Muted text, labels |

---

## File Checklist

Once you've created your assets, verify you have at minimum:

- [ ] `boot/splash.png` — Boot menu background
- [ ] `plymouth/logo.png` — Boot animation logo
- [ ] `plymouth/background.png` — Boot animation background
- [ ] `wallpapers/nexus-default.png` — Default desktop wallpaper
- [ ] `login/background.png` — Login screen background
- [ ] `login/logo.png` — Login screen logo
- [ ] `cinnamon/menu-icon.svg` — Start menu icon
- [ ] `icons/nexus-os.svg` — Main scalable icon
- [ ] `icons/nexus-agent-symbolic.svg` — Agent applet icon

The build script will skip any missing files gracefully — only present files get applied.
