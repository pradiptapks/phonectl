# Motorola Moto G71 5G — GSI Flash & Recovery Guide

**Device:** Motorola Moto G71 5G (XT2169-1)
**Codename:** `corfur` (variant: `corfur_g`)
**Serial:** `<REDACTED>`
**Date:** June 6–7, 2026
**Author:** Pradipta Sahoo

---

## Table of Contents

1. [Device Architecture](#1-device-architecture)
   - 1.1 [Hardware Specifications](#11-hardware-specifications)
   - 1.2 [Partition Architecture](#12-partition-architecture)
   - 1.3 [Partition Layout (A/B)](#13-partition-layout-ab)
   - 1.4 [Key Block Devices](#14-key-block-devices)
   - 1.5 [Vendor Build Fingerprint (Original)](#15-vendor-build-fingerprint-original)
2. [What is a GSI?](#2-what-is-a-gsi)
3. [Prerequisites & Tools](#3-prerequisites--tools)
   - 3.1 [Required Software (Linux)](#31-required-software-linux)
   - 3.2 [Required on Device](#32-required-on-device)
   - 3.3 [USB Connection Notes (Motorola-specific)](#33-usb-connection-notes-motorola-specific)
4. [Successful Flash Procedure (Android 16 GSI)](#4-successful-flash-procedure-android-16-gsi)
   - 4.1 [Download GSI Image](#41-download-gsi-image)
   - 4.2 [Enter Fastbootd Mode](#42-enter-fastbootd-mode)
   - 4.3 [Flash Images](#43-flash-images)
   - 4.4 [Post-Flash Verification](#44-post-flash-verification)
5. [Available GSI Versions (as of June 2026)](#5-available-gsi-versions-as-of-june-2026)
6. [Security Patch Updates Without Data Loss](#6-security-patch-updates-without-data-loss)
7. [What Went Wrong — Failure Analysis](#7-what-went-wrong--failure-analysis)
   - 7.1 [QPR2 Flash Attempt (Failed)](#71-qpr2-flash-attempt-failed)
   - 7.2 [Magisk Root Attempt (Caused Boot Brick)](#72-magisk-root-attempt-caused-boot-brick)
   - 7.3 [Recovery Attempts (All Failed)](#73-recovery-attempts-all-failed)
   - 7.4 [Successful Recovery (Next Morning)](#74-successful-recovery-next-morning)
8. [Firmware Sources Reference](#8-firmware-sources-reference)
9. [Lessons Learned & Best Practices](#9-lessons-learned--best-practices)
10. [Quick Recovery Cheatsheet](#10-quick-recovery-cheatsheet)
11. [Current Working Configuration (June 7, 2026)](#11-current-working-configuration-june-7-2026)

---

## 1. Device Architecture

### 1.1 Hardware Specifications

| Component | Details |
|-----------|---------|
| **SoC** | Qualcomm Snapdragon 695 (SM6375, platform: `holi`) |
| **CPU** | 8 cores ARM64 (6× Cortex-A55 + 2× Cortex-A78), kernel `5.4.233-moto` |
| **Architecture** | `arm64-v8a` |
| **RAM** | ~5.3 GB usable (6 GB physical) |
| **Storage** | 128 GB internal |
| **GPU** | Adreno 619, OpenGL ES 3.2, Vulkan 1.1 |
| **Display** | 1080×2400, 60Hz, 420dpi |
| **Encryption** | FBE (File-Based Encryption) |

### 1.2 Partition Architecture

| Feature | Value |
|---------|-------|
| **Partition Scheme** | A/B (dual slots: `_a` and `_b`) |
| **Dynamic Partitions** | Yes (`super` partition contains `system`, `vendor`, `product`) |
| **Project Treble** | Enabled |
| **VNDK Version** | 30 (shipped with Android 11) |
| **First API Level** | 30 (Android 11) |
| **Bootloader** | Unlocked (verified boot state: `orange`) |
| **Bootloader Version** | `MBM-3.0-uefi-9fb30f12f3c-240103` |

### 1.3 Partition Layout (A/B)

```
boot_a / boot_b          — Kernel + ramdisk (96 MB each)
vendor_boot_a / _b       — Device-specific ramdisk (96 MB each)
dtbo_a / dtbo_b           — Device tree blob overlays (24 MB each)
vbmeta_a / vbmeta_b       — Verified boot metadata (8 KB each)
system_a / system_b       — OS system image (inside super, ~3.2 GB)
vendor_a / vendor_b       — Vendor HAL (inside super)
product_a / product_b     — Product partition (inside super)
userdata                  — User data (shared between slots)
```

### 1.4 Key Block Devices

| Partition | Block Device |
|-----------|-------------|
| boot_a | `/dev/block/sdd18` |
| boot_b | `/dev/block/sdd46` |
| super (dynamic) | `/dev/block/by-name/super` |

### 1.5 Vendor Build Fingerprint (Original)

```
motorola/corfur_g/corfur:11/S2RUBS32.51-15-9-17/<hash>:user/release-keys
```

---

## 2. What is a GSI?

A **Generic System Image (GSI)** is a "pure Android" system image built by Google that can run on any Project Treble-compliant device. It replaces only the `system` partition — the device's original `boot`, `vendor`, `vendor_boot`, and `dtbo` partitions remain untouched.

**Key implications:**
- OTA updates do NOT work on GSI (Google's servers don't recognize the device)
- The kernel remains from the original firmware (Motorola's `5.4.233-moto`)
- Hardware compatibility depends on the vendor HAL, not the GSI version
- Updates require manual re-flash of the system partition

---

## 3. Prerequisites & Tools

### 3.1 Required Software (Linux)

```bash
sudo apt install adb fastboot
pip install payload_dumper    # For extracting images from Motorola firmware
```

### 3.2 Required on Device

- **Bootloader unlocked** (request code from Motorola's official unlock page)
- **USB Debugging enabled** (Settings → Developer Options → USB Debugging)
- Device authorized for ADB (`adb devices` shows `device`, not `unauthorized`)

### 3.3 USB Connection Notes (Motorola-specific)

- Motorola's low-level bootloader (`AP Fastboot Flash Mode`) often does NOT establish USB data connection — `fastboot devices` returns empty
- **Workaround:** Use `fastbootd` (userspace fastboot) instead — navigate via Volume buttons to Recovery → Reboot to fastbootd
- If device disappears from USB after mode switch, **unplug and replug the cable**
- Motorola USB IDs:
  - `22b8:2e76` — ADB mode (normal Android)
  - `22b8:2e81` — Bootloader mode
  - `22b8:2e82` — MTP/charging mode (USB debugging off)
  - `18d1:4ee0` — Fastbootd mode

---

## 4. Successful Flash Procedure (Android 16 GSI)

### 4.1 Download GSI Image

**Source:** [Google GSI Releases](https://developer.android.com/topic/generic-system-image/releases)

```bash
mkdir -p /tmp/gsi_flash && cd /tmp/gsi_flash

# Android 16 (Baklava) stable — ARM64 with GMS
curl -L -o gsi_gms_arm64.zip \
  "https://dl.google.com/developers/android/baklava/images/gsi/gsi_gms_arm64-exp-BP2A.250605.031.A3-13578795-38e52cb0.zip"

# Verify checksum
sha256sum gsi_gms_arm64.zip
# Expected: 38e52cb0a3331a5ee0c653a4da2401ce74598a955acbd00aa85b6326036154c5

# Extract
unzip gsi_gms_arm64.zip
# Produces: system.img (~3.2 GB), vbmeta.img, build.prop
```

### 4.2 Enter Fastbootd Mode

```bash
adb reboot fastboot
# Wait ~15 seconds
fastboot devices          # Should show device in fastbootd
fastboot getvar is-userspace  # Should return "yes"
```

### 4.3 Flash Images

```bash
cd /tmp/gsi_flash

# Step 1: Disable verified boot
fastboot flash vbmeta vbmeta.img --disable-verity --disable-verification

# Step 2: Flash system (use -S 128M to avoid USB transfer errors)
fastboot flash system system.img -S 128M

# Step 3: Wipe userdata (REQUIRED for major version upgrades)
fastboot -w

# Step 4: Reboot
fastboot reboot
```

**First boot takes 2–5 minutes.** The phone will show the setup wizard.

### 4.4 Post-Flash Verification

```bash
adb shell getprop ro.build.version.release          # Should show: 16
adb shell getprop ro.build.version.security_patch    # Should show: 2025-06-05
adb shell getprop ro.build.display.id                # Should show: BP2A.250605.031.A3
```

---

## 5. Available GSI Versions (as of June 2026)

| Version | Build | Security Patch | Status |
|---------|-------|---------------|--------|
| Android 16 (Baklava) | BP2A.250605.031.A3 | June 2025 | **Stable — CONFIRMED WORKING** |
| Android 16 QPR1 | BP3A.250905.014 | September 2025 | Stable |
| Android 16 QPR2 | BP4A.251205.006 | December 2025 | Stable — **FAILED on this device** (boot loop) |
| Android 16 QPR3 | — | — | Beta |
| Android 17 | — | — | Beta |

> **WARNING:** QPR2 (BP4A.251205.006) is NOT compatible with this device's vendor partition
> (VNDK 30, Android 11 vendor). It causes a boot loop even with a data wipe. Stick to the
> base Android 16 GSI (BP2A.250605.031.A3).

---

## 6. Security Patch Updates Without Data Loss

For minor updates within the same Android version (e.g., June → September patch), data wipe is NOT required:

```bash
# Download newer GSI, extract system.img, then:
adb reboot fastboot
fastboot flash vbmeta vbmeta.img --disable-verity --disable-verification
fastboot flash system system.img -S 128M
fastboot reboot    # NO -w flag = no data loss
```

> **IMPORTANT:** Major version jumps (Android 16 → 17) WILL require a data wipe (`fastboot -w`).

---

## 7. What Went Wrong — Failure Analysis

### 7.1 QPR2 Flash Attempt (Failed)

**Action:** Flashed Android 16 QPR2 (BP4A.251205.006) system without data wipe.
**Result:** Phone stuck at Moto boot logo.
**Root Cause:** QPR2 expects a newer vendor interface than VNDK 30. The data partition format was also incompatible.
**Recovery:** Factory reset from recovery, then reflash base Android 16 GSI.

### 7.2 Magisk Root Attempt (Caused Boot Brick)

**Goal:** Root the phone using Magisk to get admin access.

**The chicken-and-egg problem:**
- Magisk needs to patch the `boot.img` currently on the device
- Reading the boot partition (`/dev/block/sdd18`) requires root access
- Without root, we cannot extract the boot.img to patch it

**What was tried:**

| Step | Action | Result |
|------|--------|--------|
| 1 | `adb shell dd if=/dev/block/sdd18 ...` | **Failed** — permission denied (shell user cannot read block devices) |
| 2 | `adb shell cat /dev/block/by-name/boot_a ...` | **Failed** — same permission issue |
| 3 | `adb shell run-as com.topjohnwu.magisk dd ...` | **Failed** — app context cannot access block devices |
| 4 | `fastboot fetch boot_a` | **Failed** — command not supported on this device |
| 5 | Downloaded LineageOS 20 boot.img from [GitHub moto-corfur](https://github.com/moto-corfur/releases/releases/download/lin20v2/boot.img) | Downloaded successfully (96 MB) |
| 6 | Pushed boot.img to phone, patched with Magisk CLI tools | **Patched successfully** |
| 7 | Flashed Magisk-patched LineageOS boot.img via fastboot | **BOOT LOOP** — phone stuck at Moto logo |

**Root Cause:** The LineageOS boot.img contains a different kernel (built for LineageOS/Android 13) with a different ramdisk. The kernel was incompatible with the Android 16 GSI system partition. The ramdisk init scripts expected LineageOS system properties that don't exist in the GSI.

### 7.3 Recovery Attempts (All Failed)

| Attempt | Action | Result |
|---------|--------|--------|
| 1 | Reflashed Android 16 GSI system only | **Failed** — boot_a still had LineageOS kernel |
| 2 | Switched to slot B (`fastboot set_active b`) + flashed GSI to system_b | **Failed** — boot_b was also corrupted/empty |
| 3 | Flashed unpatched LineageOS boot.img (without Magisk) | **Failed** — still wrong kernel for GSI |
| 4 | Flashed LineageOS boot + vendor_boot + dtbo | **Failed** — kernel incompatibility persists |
| 5 | Sideloaded full LineageOS ROM via recovery | **Failed** — stock recovery incompatible with LineageOS OTA zip format |
| 6 | Extracted LineageOS system.img via `payload_dumper`, flashed via fastboot | **Failed** — phone went to AP Fastboot Flash Mode |
| 7 | Tried downloading Motorola stock firmware from various sources | **Failed** — Google Drive rate limits, broken links |

### 7.4 Successful Recovery (Next Morning)

**Source:** [Lolinet Mirrors](https://mirrors.lolinet.com/firmware/lenomola/corfur/official/) — the most reliable source for Motorola firmware.

**Download URL:**
```
https://mirrors-obs-1.lolinet.com/firmware/lenomola/2021/corfur/official/RETIN/XT2169-1_CORFUR_RETIN_12_S2RUBS32.51-15-3-19_subsidy-DEFAULT_regulatory-DEFAULT_cid50_CFC.xml.zip
```

**File:** 2.9 GB zip containing individual partition images (NOT payload.bin format).

**Extraction:**
```bash
mkdir -p /tmp/moto_recovery && cd /tmp/moto_recovery
# Download firmware (took ~10 minutes at ~5 MB/s)
curl -L -o firmware.zip "<URL above>"

# Extract only boot-related images (no need for full super partition)
unzip firmware.zip boot.img vendor_boot.img dtbo.img vbmeta.img
```

**Flash procedure:**
```bash
# Enter fastbootd
# (from AP Fastboot: Volume → Recovery → then navigate to fastbootd)

# Flash original Motorola boot partitions
fastboot flash boot boot.img
fastboot flash vendor_boot vendor_boot.img
fastboot flash dtbo dtbo.img
fastboot flash vbmeta vbmeta.img --disable-verity --disable-verification

# Flash Android 16 GSI system
fastboot flash system /tmp/gsi_flash/system.img -S 128M

# Wipe data and reboot
fastboot -w
fastboot reboot
```

**Result:** Phone booted successfully into Android 16 with the original Motorola kernel.

---

## 8. Firmware Sources Reference

| Source | URL | Notes |
|--------|-----|-------|
| **Lolinet Mirrors** (BEST) | `mirrors.lolinet.com/firmware/lenomola/corfur/official/` | Direct download, no captcha, multiple regions (RETIN=India, RETBR=Brazil, RETEU=Europe) |
| Google GSI Releases | `developer.android.com/topic/generic-system-image/releases` | Official GSI images |
| motostockrom.com | `motostockrom.com/motorola-moto-g71-5g-xt2169-1` | Has firmware but behind download pages |
| romstockbr.com | `romstockbr.com` | Has individual boot.img on MediaFire (Brazilian Portuguese site) |
| stockrom.net | `stockrom.net/category/motorola/moto-g71-5g` | Mirror of romstockbr, same files |
| LineageOS (corfur) | `github.com/moto-corfur/releases` | Community ROM — boot.img is NOT compatible with GSI |

### Lolinet Directory Structure

```
mirrors.lolinet.com/firmware/lenomola/corfur/official/
├── RETIN/          ← India (RETINALL)
│   ├── XT2169-1_CORFUR_RETIN_11_RRUB31.Q3-71-68_..._CFC.xml.zip     (Android 11)
│   └── XT2169-1_CORFUR_RETIN_12_S2RUBS32.51-15-3-19_..._CFC.xml.zip (Android 12) ← USED
├── RETBR/          ← Brazil
├── RETEU/          ← Europe
├── RETAIL/         ← Generic retail
└── blankflash/     ← Emergency recovery files
```

### Motorola Firmware ZIP Contents

```
firmware.zip (2.9 GB)
├── boot.img              (96 MB)  ← Kernel + ramdisk
├── vendor_boot.img       (96 MB)  ← Device-specific ramdisk
├── dtbo.img              (24 MB)  ← Device tree overlays
├── vbmeta.img            (8 KB)   ← Verified boot metadata
├── bootloader.img        (22 MB)  ← Bootloader (DO NOT flash unless necessary)
├── radio.img             (144 MB) ← Modem firmware
├── super.img_sparsechunk.0–11    ← Stock system/vendor/product
├── flashfile.xml                  ← Flash script configuration
└── servicefile.xml                ← Service configuration
```

---

## 9. Lessons Learned & Best Practices

### ALWAYS Do Before Any Boot Partition Modification

```bash
# 1. Back up current boot.img BEFORE any changes
adb reboot fastboot
# Unfortunately `fastboot fetch` is not supported on this device.
# Alternative: download matching stock firmware and keep boot.img archived.

# 2. Save the stock firmware boot images locally
mkdir -p ~/moto_g71_backup/
cp boot.img vendor_boot.img dtbo.img vbmeta.img ~/moto_g71_backup/
```

### Rules

1. **NEVER flash a boot.img from a different ROM** (e.g., LineageOS boot on GSI system). The kernel and ramdisk must match the system they're designed for, or the device won't boot.

2. **NEVER flash QPR2 or higher GSI versions** on a device with VNDK 30 vendor. Stick to the base Android 16 GSI.

3. **For Magisk rooting on GSI**, the ONLY correct approach:
   - Download the **exact** Motorola stock firmware matching the device
   - Extract `boot.img` from it
   - Patch it with Magisk (on-device or via `magiskboot` CLI)
   - Flash the patched image
   - The original Motorola boot.img kernel IS compatible with Android 16 GSI

4. **Keep a copy of the stock firmware** (or at minimum `boot.img`, `vendor_boot.img`, `dtbo.img`) for recovery. The Lolinet mirror is the most reliable source.

5. **Use `-S 128M`** when flashing system images to avoid USB transfer errors (`-S 256M` failed on this device).

6. **Motorola bootloader USB quirks:** If `fastboot devices` returns empty in the low-level bootloader, switch to `fastbootd` (userspace fastboot) and replug the USB cable.

---

## 10. Quick Recovery Cheatsheet

If the phone is stuck in a boot loop:

```bash
# 1. Enter fastbootd
#    - Hold Power + Volume Down for 15 seconds
#    - Navigate to Recovery Mode (Volume buttons + Power)
#    - From recovery: select "Enter fastboot" or "Reboot to bootloader"
#    - If in fastbootd, you should see options like "Reboot system now",
#      "Enter recovery", "Reboot to bootloader", "Power off"

# 2. Replug USB cable (Motorola USB quirk)

# 3. Verify connection
fastboot devices

# 4. Flash stock boot partitions (keep these files saved!)
fastboot flash boot ~/moto_g71_backup/boot.img
fastboot flash vendor_boot ~/moto_g71_backup/vendor_boot.img
fastboot flash dtbo ~/moto_g71_backup/dtbo.img
fastboot flash vbmeta ~/moto_g71_backup/vbmeta.img --disable-verity --disable-verification

# 5. Flash GSI system
fastboot flash system system.img -S 128M

# 6. Wipe and reboot
fastboot -w
fastboot reboot
```

---

## 11. Current Working Configuration (June 7, 2026)

| Layer | Image | Source |
|-------|-------|--------|
| **boot_a** | Motorola stock `S2RUBS32.51-15-3-19` | Lolinet RETIN firmware |
| **vendor_boot_a** | Motorola stock `S2RUBS32.51-15-3-19` | Lolinet RETIN firmware |
| **dtbo_a** | Motorola stock `S2RUBS32.51-15-3-19` | Lolinet RETIN firmware |
| **vbmeta_a** | GSI vbmeta (verity disabled) | Google GSI zip |
| **system_a** | Android 16 GSI `BP2A.250605.031.A3` | Google GSI releases |
| **vendor_a** | Motorola stock (untouched) | Original device |
| **Kernel** | `5.4.233-moto` | From boot.img |
| **Active Slot** | `_a` | — |

---

*Document generated from flash session logs. Keep this file and the backup images for future reference.*
