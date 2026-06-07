# phonectl — Universal Android Phone Lifecycle Manager

A Python CLI/TUI tool that automates Android phone lifecycle management — flash, backup, root, update, and recover — with a vendor-plugin architecture.

## Features

- **Device Detection** — Auto-detect connected Android devices and identify vendor/model
- **GSI Flash** — Download and flash Generic System Images with safety checks
- **Backup & Restore** — Back up boot partitions before any modification; restore on failure
- **Security Updates** — Update GSI security patches without data loss
- **Recovery** — Emergency recovery from boot loops using stock firmware
- **Vendor Plugins** — Extensible architecture; Motorola included as reference, add Samsung/Pixel/others
- **Safety First** — Pre-flash compatibility validation, USB watchdog, automatic rollback

## Installation

```bash
git clone https://github.com/psahoo/phone-repair.git
cd phone-repair
pip install -e .
```

## Quick Start

```bash
# Show connected device info
phonectl info

# Backup boot partitions before any changes
phonectl backup --boot

# Flash Android 16 GSI
phonectl flash gsi --version BP2A.250605.031.A3

# Update security patch (no data loss)
phonectl update

# Recover a bricked phone
phonectl recover

# Interactive TUI mode
phonectl tui
```

## Supported Vendors

| Vendor | Status | Plugin |
|--------|--------|--------|
| Motorola | Reference implementation | `phonectl.vendors.motorola` |
| Google Pixel | Stub (contributions welcome) | `phonectl.vendors.google` |
| Samsung | Stub (contributions welcome) | `phonectl.vendors.samsung` |

## Requirements

- Python 3.10+
- `adb` and `fastboot` installed and on PATH
- USB cable (data-capable, not charge-only)
- Unlocked bootloader on the target device

## Project Structure

```
phonectl/
├── cli.py              # Click CLI commands
├── tui.py              # Rich interactive TUI
├── core/
│   ├── adb.py          # ADB subprocess wrapper
│   ├── fastboot.py     # Fastboot subprocess wrapper
│   ├── device.py       # Device detection and management
│   ├── safety.py       # Pre-flash safety checks and validation
│   └── backup.py       # Backup/restore boot partitions
├── vendors/
│   ├── base.py         # BaseVendorPlugin abstract class
│   ├── motorola.py     # Motorola reference plugin
│   ├── google.py       # Google Pixel plugin (stub)
│   └── samsung.py      # Samsung plugin (stub)
├── firmware/
│   ├── gsi.py          # GSI version listing and compatibility
│   ├── sources.py      # Firmware source registry
│   └── downloader.py   # Download with progress and checksum
└── config/
    ├── vendors.yaml    # Vendor detection rules
    └── gsi_versions.yaml  # GSI compatibility matrix
```

## Documentation

- [Moto G71 5G GSI Flash Guide](docs/Moto_G71_5G_GSI_Flash_Guide.md) — Real-world reference from the session that inspired this tool

## License

Apache License 2.0
