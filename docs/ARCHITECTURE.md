# phonectl — Architecture Document

**Version:** 0.1.0
**Last Updated:** June 7, 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Module Reference](#3-module-reference)
4. [Data Flow](#4-data-flow)
5. [Safety Architecture](#5-safety-architecture)
6. [Configuration System](#6-configuration-system)
7. [Vendor Plugin System](#7-vendor-plugin-system)
8. [Feature Status](#8-feature-status)
9. [Known Issues and Fixes](#9-known-issues-and-fixes)
10. [Future Enhancements](#10-future-enhancements)

---

## 1. Overview

`phonectl` is a Python CLI/TUI tool for Android phone lifecycle management, targeting devices that are out of warranty and no longer receiving OEM updates. It provides:

- Device detection and vendor identification
- Hardware/firmware compatibility analysis
- GSI (Generic System Image) flashing with safety guards
- Security auditing and hardening
- Performance tuning
- Storage management and bloatware removal
- Boot partition backup/restore and recovery

The tool communicates with Android devices over USB via `adb` and `fastboot` — no root required for most operations.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     User Interface Layer                         │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │   CLI (click) │  │  TUI (rich)  │                             │
│  │   cli.py      │  │  tui.py      │                             │
│  └──────┬───────┘  └──────┬───────┘                             │
│         └────────┬────────┘                                     │
├──────────────────┼──────────────────────────────────────────────┤
│                  │         Core Engine                           │
│  ┌───────────────▼──────────────┐                               │
│  │       DeviceManager          │  device.py                    │
│  │  detect → identify → route   │                               │
│  └──┬────┬────┬────┬────┬──────┘                               │
│     │    │    │    │    │                                        │
│  ┌──▼──┐ │ ┌──▼──┐ │ ┌──▼──────────┐                           │
│  │ ADB │ │ │ FB  │ │ │ VendorPlugin│  vendors/                 │
│  │     │ │ │     │ │ │ (Motorola,  │                            │
│  └─────┘ │ └─────┘ │ │  Pixel,    │                            │
│          │         │ │  Samsung)  │                            │
│  ┌───────▼──┐  ┌───▼──────┐ └────────────┘                     │
│  │SafetyGrd │  │BackupMgr │                                    │
│  │safety.py │  │backup.py │                                    │
│  └──────────┘  └──────────┘                                    │
├─────────────────────────────────────────────────────────────────┤
│                    Feature Modules                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │  Audit   │ │  Tune    │ │ Storage  │ │ Security │           │
│  │audit.py  │ │tune.py   │ │storage.py│ │security.py│          │
│  │+stalker  │ │          │ │          │ │          │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────────┤
│                    Firmware Layer                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                        │
│  │  GSI     │ │ Sources  │ │Downloader│                        │
│  │ gsi.py   │ │sources.py│ │downloader│                        │
│  │+recommend│ │(lolinet) │ │.py       │                        │
│  └──────────┘ └──────────┘ └──────────┘                        │
├─────────────────────────────────────────────────────────────────┤
│                    Configuration (YAML)                          │
│  vendors.yaml │ gsi_versions.yaml │ warranty.yaml               │
│  stalkerware.yaml │ profiles.yaml │ bloatware.yaml              │
│  protected_apps.yaml                                            │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **No root required** — all primary features work via standard ADB
2. **Safety first** — destructive operations require confirmation, backups are enforced
3. **Vendor-agnostic** — plugin architecture isolates vendor-specific behaviour
4. **Config-driven** — behaviour controlled by YAML files, not hardcoded values
5. **Offline-capable** — compatibility checks and audits work without internet

---

## 3. Module Reference

### Core (`phonectl/core/`)

| Module | Purpose | Lines |
|--------|---------|-------|
| `adb.py` | ADB subprocess wrapper with input sanitization | Shell, getprop, push/pull, reboot, sideload |
| `fastboot.py` | Fastboot wrapper for bootloader operations | Flash, getvar, wipe, set_active, reboot |
| `device.py` | Device detection, identification, property gathering | DeviceManager, DeviceInfo dataclass |
| `safety.py` | Pre-flash validation — 14 compatibility checks | VNDK matrix, kernel gate, hardware requirements |
| `backup.py` | Boot partition backup/restore with metadata | Timestamped archives, latest symlink |
| `audit.py` | Security audit + warranty estimation (21 checks) | WarrantyEstimator, SecurityScanner |
| `stalkerware.py` | Stalkerware detection against package database | Scans installed packages vs ~150 known threats |
| `tune.py` | Performance tuning profiles | 4 profiles, ART compilation, setting backup |
| `reset.py` | Factory reset flows with safety confirmations | Factory, wipe, cache clear, per-app clear |
| `storage.py` | Storage analysis, cleanup, bloatware management | 3-tier cleanup, disable/enable with undo log |
| `security.py` | Network/phone security checks + hardening | 23 checks, scoring 0-100, auto-fix |

### Vendors (`phonectl/vendors/`)

| Module | Status | Capabilities |
|--------|--------|-------------|
| `base.py` | Complete | Abstract base class — all vendors implement this |
| `motorola.py` | Complete | Full flash sequences, lolinet firmware, USB quirks |
| `google.py` | Stub | Detection only (with GSI false-positive fix) |
| `samsung.py` | Stub | Detection only (notes Odin/Heimdall requirement) |

### Firmware (`phonectl/firmware/`)

| Module | Purpose |
|--------|---------|
| `gsi.py` | GSI version registry, compatibility check, recommendation engine |
| `sources.py` | Firmware source registry (lolinet mirrors, Google CDN) |
| `downloader.py` | HTTP download with rich progress bar, SHA-256 verification |

---

## 4. Data Flow

### Device Detection Flow

```
ADB connected?
  ├── Yes → Read 30+ device properties → Build DeviceInfo
  │         ├── Match vendor plugin (manufacturer → codename fallback)
  │         └── Return DeviceInfo + vendor plugin
  ├── Unauthorized → Return UNAUTHORIZED state
  └── No → Try fastboot
            ├── Found → Read getvar properties → Return FASTBOOT/FASTBOOTD
            └── Not found → Return DISCONNECTED
```

### GSI Flash Flow

```
phonectl flash gsi
  ├── Detect device → DeviceInfo
  ├── Evaluate ALL GSI versions → Recommendation engine (score 0-100)
  ├── Auto-select RECOMMENDED version (or user-specified)
  ├── Block if INCOMPATIBLE/BROKEN → Show alternative
  ├── Run 14 safety checks → SafetyReport
  ├── Confirm destructive operation
  ├── Download GSI (with progress + SHA-256)
  ├── Reboot to fastbootd
  ├── Execute vendor-specific flash sequence
  │   ├── Flash vbmeta (disable verification)
  │   ├── Flash system (128MB chunks)
  │   ├── Wipe userdata (if major version change)
  │   └── Reboot
  └── Verify boot (check Android version via ADB)
```

### Security Audit Flow

```
phonectl audit
  ├── Detect device → DeviceInfo
  ├── WarrantyEstimator
  │   ├── First API level → ship year
  │   ├── Manufacturer → OEM warranty period
  │   └── Vendor patch age → support status
  ├── SecurityScanner (17 non-root checks)
  │   ├── OS Integrity (4): build tags, verified boot, build type, SELinux
  │   ├── Root/Mods (4): su, Magisk, encryption, custom ROM
  │   ├── Stalkerware (3): package scan, device admin, accessibility
  │   ├── Permissions (3): dangerous perms, sideload, developer options
  │   └── Network (3): ADB over WiFi, persistent TCP, services count
  ├── [Optional] Root deep scan (4 checks with --deep)
  ├── Calculate risk level (LOW/MEDIUM/HIGH/CRITICAL)
  └── Display report + export (--export json/md)
```

---

## 5. Safety Architecture

### Protection Layers

| Layer | What It Protects | Implementation |
|-------|-----------------|----------------|
| Input sanitization | Shell injection via ADB | `_validate_safe_string()` rejects metacharacters |
| VNDK compatibility matrix | Flashing incompatible GSI | `VNDK_GSI_COMPAT` dict in safety.py |
| Kernel version gate | Android 13+ on kernel < 4.19 | `MIN_KERNEL_FOR_ANDROID13` check |
| Protected app whitelist | Disabling critical system apps | `protected_apps.yaml` checked before every disable |
| Backup enforcement | Losing original boot images | Pre-flash check verifies backup exists |
| USB monitoring | Cable disconnect during flash | `monitor_usb_during_flash()` checks lsusb |
| Double confirmation | Accidental factory reset | User must type `RESET` (not just `yes`) |
| Dry-run mode | Previewing destructive operations | `--dry-run` flag on cleanup, bloatware, hardening |
| Undo log | Rollback disabled bloatware | `~/.phonectl/disabled_apps.json` tracks changes |
| Setting backup | Rollback tune/security changes | `~/.phonectl/tune_backup.json`, `security_backup.json` |

### Data Stored Locally (`~/.phonectl/`)

| File | Purpose | Created By |
|------|---------|------------|
| `backups/<codename>/<timestamp>/` | Boot partition images + metadata | `phonectl backup create` |
| `disabled_apps.json` | List of apps disabled by bloatware manager | `phonectl storage bloatware disable` |
| `tune_backup.json` | Original performance settings before tuning | `phonectl tune --profile` |
| `security_backup.json` | Original security settings before hardening | `phonectl security --harden` |

---

## 6. Configuration System

All configuration is YAML-based under `phonectl/config/`:

| File | Purpose | Entries |
|------|---------|--------|
| `vendors.yaml` | Vendor detection rules (USB IDs, properties, quirks) | 5 vendors |
| `gsi_versions.yaml` | GSI version registry with compatibility matrix | 14 versions (Android 11-17) |
| `warranty.yaml` | OEM warranty periods and API-to-year mapping | 20 manufacturers |
| `stalkerware.yaml` | Known stalkerware/spyware package database | ~150 threat families |
| `profiles.yaml` | Performance tuning profiles | 4 profiles |
| `bloatware.yaml` | Known bloatware per vendor | 50+ apps across 6 vendors |
| `protected_apps.yaml` | System-critical apps that must never be disabled | 30+ packages |

### Extension Point

Users and contributors can add new entries by editing YAML files — no code changes required for:
- Adding new GSI versions
- Adding new stalkerware signatures
- Adding new bloatware entries
- Adding new vendor detection rules

---

## 7. Vendor Plugin System

### Interface (BaseVendorPlugin)

Every vendor plugin must implement:

```python
class BaseVendorPlugin(ABC):
    name: str                           # Display name
    usb_vendor_ids: list[str]           # USB VIDs for detection
    detect(info) -> bool                # Does this plugin handle this device?
    get_boot_partitions() -> list[str]  # Partitions in the boot set
    get_flash_sequence(...) -> list[FlashStep]  # Ordered flash steps
    get_firmware_source(info) -> FirmwareSource  # Where to download firmware
    get_usb_quirks() -> dict            # Known USB/fastboot quirks
```

### Plugin Resolution Order

1. DeviceManager iterates registered plugins
2. Each plugin's `detect()` is called with DeviceInfo
3. First match wins — plugins are registered in order: Motorola, Google, Samsung
4. Motorola checks vendor fingerprint and codename (catches GSI-on-Motorola)
5. Google checks vendor fingerprint to avoid false positives on GSI

### Adding a New Vendor

1. Create `phonectl/vendors/yourvendor.py` implementing `BaseVendorPlugin`
2. Register in `cli.py` → `_create_device_manager()`
3. Add detection rules to `config/vendors.yaml`
4. Add bloatware entries to `config/bloatware.yaml` (optional)

---

## 8. Feature Status

### Complete (Implemented and Tested)

| Feature | Command | Checks/Items | Status |
|---------|---------|-------------|--------|
| Device detection | `phonectl info` | 25+ properties | Stable |
| Compatibility check | `phonectl check` | 14 hardware/firmware checks | Stable |
| GSI recommendations | `phonectl recommend` | 14 GSI versions scored | Stable |
| GSI flash | `phonectl flash gsi` | Auto-select + safety + flash | Stable |
| GSI update | `phonectl update` | No-wipe security patch update | Stable |
| Boot backup/restore | `phonectl backup` | Timestamped archive + restore | Stable |
| Emergency recovery | `phonectl recover` | Auto-find backup + flash | Stable |
| Firmware listing | `phonectl firmware list` | Android 11-17, 14 versions | Stable |
| Firmware regions | `phonectl firmware regions` | Lolinet mirror query | Stable |
| Security audit | `phonectl audit` | 21 checks (17 non-root + 4 root) | Stable |
| Warranty estimation | `phonectl audit` | API-based age + OEM support lookup | Stable |
| Stalkerware scan | `phonectl audit` | ~150 known package signatures | Stable |
| Security guard | `phonectl security` | 23 checks, 0-100 scoring | Stable |
| Security hardening | `phonectl security --harden` | Auto-fix with dry-run + backup | Stable |
| Performance tuning | `phonectl tune` | 4 profiles + ART compile | Stable |
| Storage management | `phonectl storage` | 3-tier cleanup + bloatware | Stable |
| Factory reset | `phonectl reset` | 4 reset modes with safety | Stable |
| Interactive TUI | `phonectl tui` | 12-item menu | Stable |

### Vendor Plugin Status

| Vendor | Detection | Flash | Recovery | Firmware Download |
|--------|-----------|-------|----------|-------------------|
| Motorola | Full (codename + fingerprint) | Full | Full | Lolinet mirrors |
| Google Pixel | Detection only | Not implemented | Not implemented | Stub |
| Samsung | Detection only | Not implemented (needs Odin) | Not implemented | Stub |
| OnePlus | Config only | Not implemented | Not implemented | Not started |
| Xiaomi | Config only | Not implemented | Not implemented | Not started |

---

## 9. Known Issues and Fixes

### Fixed (v0.1.0)

| # | Issue | Fix Applied |
|---|-------|-------------|
| 1 | Shell injection in `adb.getprop()` and `shell()` | Added `_validate_safe_string()` + `shell_safe()` method |
| 2 | `*.log` deletion in safe cleanup tier | Moved to deep tier only |
| 5 | Google Pixel false-positive on GSI devices | Added vendor fingerprint check + codename verification |
| 11 | API 37 (Android 17) missing from API_TO_YEAR | Added to audit.py and safety.py |
| 12 | Codename detection only from one property | Added `ro.product.device`, `ro.product.board`, `ro.build.product` fallbacks |

### Known Remaining Issues

| # | Issue | Priority | Status |
|---|-------|----------|--------|
| 4 | Download resume not implemented (docstring claims it is) | Medium | Backlog |
| 6 | No unit tests | High | Next sprint |
| 7 | Duplicate `_create_device_manager` in cli.py and tui.py | Low | Backlog |
| 8 | TUI invokes CLI via Click context (fragile) | Medium | Next sprint |
| 9 | Module-level Console() instances | Low | Backlog |
| 10 | setup.py should be pyproject.toml | Low | Backlog |
| 13 | YAML config files not schema-validated | Low | Backlog |
| 14 | `phonectl check` requires connected device (no offline mode) | Medium | Backlog |

---

## 10. Future Enhancements

### Priority 1 — Next Sprint

| Enhancement | Description | Effort |
|-------------|-------------|--------|
| Unit tests | Test recommendation engine, VNDK matrix, kernel parsing, stalkerware matching | Medium |
| TUI Click decoupling | TUI handlers should call core functions, not re-invoke Click | Medium |
| Offline compatibility check | `phonectl check --vndk 30 --kernel 4.19 --ram 4096` without device | Medium |

### Priority 2 — Short-term Roadmap

| Enhancement | Description | Effort |
|-------------|-------------|--------|
| Download resume | Range-header support for interrupted GSI downloads | Medium |
| Google Pixel plugin | Full flash sequence for Pixel devices | Medium |
| pyproject.toml migration | Replace setup.py with modern packaging | Low |
| Config schema validation | Validate YAML files against schema on load | Low |
| App usage analysis | Use `dumpsys usagestats` to identify unused apps | Medium |

### Priority 3 — Long-term Vision

| Enhancement | Description | Effort |
|-------------|-------------|--------|
| Samsung plugin (Heimdall) | Full flash support via Heimdall/Odin protocol | High |
| Xiaomi plugin | MI unlock integration + flash support | High |
| OnePlus plugin | MSM download mode support | High |
| Multi-device management | Manage fleet of devices simultaneously | High |
| Magisk root automation | Full Magisk rooting workflow with correct boot.img sourcing | High |
| CI/CD integration | `phonectl security --score` as a CI check for device compliance | Medium |
| Web dashboard | Browser-based UI for device management | High |
| Scheduled scans | Cron-based periodic audit and update checks | Medium |
| OTA-like updates | Background GSI update to inactive slot, similar to A/B OTA | High |

### Priority 4 — Community / Ecosystem

| Enhancement | Description |
|-------------|-------------|
| Plugin marketplace | Community-contributed vendor plugins |
| Stalkerware DB updates | Automated pull from threat intelligence feeds |
| Device compatibility reports | Crowdsourced GSI compatibility data per device model |
| Localization | Multi-language CLI/TUI support |

---

*This document reflects the state of phonectl v0.1.0 as of June 7, 2026.*
