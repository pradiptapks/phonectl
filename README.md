# phonectl — Universal Android Phone Lifecycle Manager

A Python CLI/TUI tool that automates Android phone lifecycle management — flash, backup, audit, tune, and recover — with a vendor-plugin architecture.

> **WARNING: This tool is intended for devices that are OUT OF WARRANTY and/or no longer receiving official OEM software updates.** Unlocking the bootloader, flashing GSI images, or modifying boot partitions **will void your device warranty** and may permanently brick your device if used incorrectly. The authors are not responsible for any damage to your device. **Proceed entirely at your own risk.**

## Who Is This For?

- Devices that have **reached end of life** and no longer receive security patches
- Users who want to **extend the life** of an older phone via GSI
- Anyone stuck with an **abandoned device** the OEM has stopped supporting

**Not for** devices under active warranty, enterprise/production devices, or users unfamiliar with bootloader unlocking.

## Features

- **Device Detection** — auto-detect vendor, model, hardware specs, and firmware
- **Compatibility Check** — 14 hardware/firmware checks + ranked GSI recommendations (Android 11–17)
- **GSI Flash** — download, validate, and flash with safety guards and incompatible version blocking
- **Security Audit** — warranty estimation, stalkerware scan (150+ signatures), 21 security checks
- **Security Guard** — 23-check network/lockscreen/app security assessment with 0–100 scoring and auto-hardening
- **Performance Tuning** — 4 profiles (fast/balanced/battery/gaming), ART compilation
- **Storage Management** — 3-tier cleanup, bloatware detection/removal for 6 vendors with SafetyGuard
- **Factory Reset** — safe reset flows with double confirmation, FRP warnings
- **Backup & Recovery** — boot partition backup/restore, emergency recovery from boot loops
- **Vendor Plugins** — Motorola (full), Google Pixel and Samsung (stubs), extensible for others

## Installation

```bash
# Prerequisites (Debian/Ubuntu)
sudo apt install android-tools-adb android-tools-fastboot python3.12-venv

# Install phonectl
git clone https://github.com/pradiptapks/phonectl.git
cd phonectl
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Verify
phonectl --version
```

> On Python 3.12+, if you prefer system-wide install: `pip install --break-system-packages -e .`

**Device setup:** Enable Developer Options (tap Build Number 7 times), then enable USB Debugging.

## Quick Start

```bash
# Device info and diagnostics
phonectl info                           # Show device details
phonectl check                          # Hardware compatibility + GSI recommendations
phonectl audit                          # Security audit + warranty check

# Performance and cleanup
phonectl tune --profile fast            # Speed up an old phone
phonectl storage cleanup                # Clear caches and temp files
phonectl storage bloatware disable      # Remove OEM bloatware (reversible)

# Security
phonectl security                       # Full security assessment (score 0-100)
phonectl security --harden              # Auto-fix security issues

# Flash and recovery
phonectl backup create --from-dir ./fw  # Backup boot partitions first
phonectl flash gsi                      # Flash best compatible GSI
phonectl recover --codename corfur      # Emergency recovery from boot loop

# Interactive mode
phonectl tui                            # Menu-driven TUI
```

## Commands Overview

| Category | Commands |
|----------|----------|
| **Diagnostics** | `info`, `check`, `recommend` |
| **Security** | `audit`, `security`, `security --harden` |
| **Performance** | `tune --profile`, `tune --compile` |
| **Storage** | `storage show`, `storage cleanup`, `storage bloatware` |
| **Flash** | `flash gsi`, `flash stock`, `update` |
| **Recovery** | `backup`, `recover`, `reset` |
| **Firmware** | `firmware list`, `firmware regions` |
| **Interactive** | `tui` |

For the full command reference with all flags and options, see [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).

## Supported Vendors

| Vendor | Status | Notes |
|--------|--------|-------|
| Motorola | Full support | Flash, backup, recover, firmware download |
| Google Pixel | Detection only | Contributions welcome |
| Samsung | Detection only | Uses Odin/Heimdall, not fastboot |
| OnePlus, Xiaomi | Config only | Detection rules defined, plugins not yet implemented |

## How It Works

```
phonectl
├── CLI / TUI              ← User interface (click + rich)
├── DeviceManager          ← Detects device, resolves vendor plugin
├── VendorPlugin           ← Vendor-specific flash sequences and quirks
├── SafetyGuard            ← Pre-flash validation, USB monitoring, input sanitization
├── AuditEngine            ← Warranty estimation, stalkerware scan, security checks
├── SecurityGuard          ← Network/lockscreen/app security, scoring, hardening
├── TuneEngine             ← Performance profiles, ART compilation
├── StorageAnalyzer        ← Cleanup, bloatware management with protected whitelist
├── BackupManager          ← Boot partition backup/restore
└── FirmwareManager        ← GSI download, version registry, recommendations
```

Safety is built in at every level — VNDK compatibility matrix, kernel version gating, incompatible version blocking, protected app whitelist, input sanitization, USB monitoring, double confirmations, dry-run mode, and undo logs. Born from a real incident where a Moto G71 5G was bricked during a flash attempt.

## Documentation

| Document | Description |
|----------|-------------|
| [CLI Reference](docs/CLI_REFERENCE.md) | Full command reference with all flags and options |
| [Architecture](docs/ARCHITECTURE.md) | System design, module reference, data flows, safety layers, feature status, roadmap |
| [Moto G71 5G Flash Guide](docs/Moto_G71_5G_GSI_Flash_Guide.md) | Real-world reference from the session that inspired this tool |

## Contributing

1. **New vendor plugin:** Create `vendors/yourvendor.py` implementing `BaseVendorPlugin`, register in `cli.py`
2. **New GSI versions:** Edit `config/gsi_versions.yaml` with download URL, checksum, VNDK compatibility
3. **New bloatware entries:** Edit `config/bloatware.yaml` per vendor
4. **New stalkerware signatures:** Edit `config/stalkerware.yaml`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `adb devices` empty | Enable USB debugging, replug cable, `adb kill-server && adb start-server` |
| Device `unauthorized` | Approve USB debugging prompt on phone |
| `fastboot devices` empty | Motorola quirk — use fastbootd, replug cable |
| `pip install` fails | Use venv: `python3 -m venv .venv && source .venv/bin/activate` |
| Phone stuck at boot logo | `phonectl recover --codename <device>` |
| Wrong vendor detected | GSI reports manufacturer as "Google" — detection falls back to codename |

## License

Apache License 2.0
