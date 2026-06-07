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

## Prerequisites

### System Dependencies

Install `adb`, `fastboot`, and Python venv support:

```bash
# Debian/Ubuntu
sudo apt install android-tools-adb android-tools-fastboot python3.12-venv

# Fedora/RHEL
sudo dnf install android-tools python3-virtualenv

# Arch
sudo pacman -S android-tools python
```

### Device Requirements

- **USB Debugging** enabled on the phone (Settings > Developer Options > USB Debugging)
- **Bootloader unlocked** (required for flashing — request from your OEM's unlock page)
- **USB data cable** (charge-only cables will not work)

> **How to enable Developer Options:**
> Go to **Settings > About Phone** and tap **Build Number** 7 times.
> Then go back to **Settings > System > Developer Options** and enable **USB Debugging**.

## Installation

### Recommended: Virtual Environment

```bash
git clone https://github.com/pradiptapks/phonectl.git
cd phonectl
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

To activate the environment in future terminal sessions:

```bash
source /path/to/phonectl/.venv/bin/activate
```

### Alternative: System-wide Install

If you prefer not to use a virtual environment (not recommended on managed Python environments):

```bash
git clone https://github.com/pradiptapks/phonectl.git
cd phonectl
pip install --break-system-packages -e .
```

> **Note:** On Python 3.12+ (Debian/Ubuntu), `pip install` without a venv will fail with
> `error: externally-managed-environment`. Use the virtual environment method above,
> or pass `--break-system-packages` to override.

### Verify Installation

```bash
phonectl --version
# phonectl, version 0.1.0

phonectl --help
```

## Quick Start

```bash
# Show connected device info
phonectl info

# Backup boot partitions before any changes
phonectl backup create --from-dir /path/to/firmware/

# List existing backups
phonectl backup list

# Flash Android 16 GSI (auto-selects compatible version)
phonectl flash gsi

# Flash a specific GSI version
phonectl flash gsi --version BP2A.250605.031.A3

# Update security patch without data loss
phonectl update

# Recover a bricked phone from backup
phonectl recover --codename corfur

# List available GSI versions
phonectl firmware list

# Check available firmware regions for a device
phonectl firmware regions corfur

# Interactive TUI mode
phonectl tui
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `phonectl info` | Show connected device info (model, Android version, VNDK, partitions) |
| `phonectl backup create` | Create a backup of boot partition images |
| `phonectl backup list` | List all saved backups |
| `phonectl backup restore <path>` | Restore boot partitions from a backup |
| `phonectl flash gsi` | Download and flash a GSI image |
| `phonectl flash stock` | Find stock firmware download for the device |
| `phonectl update` | Update GSI security patch without data wipe |
| `phonectl recover` | Emergency recovery from boot loop using backups |
| `phonectl firmware list` | List available GSI versions with compatibility info |
| `phonectl firmware download <id>` | Download a GSI version for offline use |
| `phonectl firmware regions <codename>` | List firmware regions available on lolinet mirrors |
| `phonectl tui` | Launch interactive TUI mode |

## Supported Vendors

| Vendor | Status | Plugin | Notes |
|--------|--------|--------|-------|
| Motorola | Reference implementation | `phonectl.vendors.motorola` | Full support — flash, backup, recover, firmware download |
| Google Pixel | Stub | `phonectl.vendors.google` | Detection only — contributions welcome |
| Samsung | Stub | `phonectl.vendors.samsung` | Detection only — uses Odin/Heimdall, not fastboot |
| OnePlus | Config only | via `vendors.yaml` | Detection rules defined, plugin not yet implemented |
| Xiaomi | Config only | via `vendors.yaml` | Detection rules defined, plugin not yet implemented |

## How It Works

### Architecture

```
phonectl
├── CLI / TUI              ← User interface (click + rich)
├── DeviceManager          ← Detects device, resolves vendor plugin
├── VendorPlugin           ← Vendor-specific flash sequences and quirks
├── SafetyGuard            ← Pre-flash validation and USB monitoring
├── BackupManager          ← Backup/restore boot partition images
└── FirmwareManager        ← GSI download, version registry, compatibility
```

### Flash Workflow

1. **Detect** device via ADB → identify vendor, model, VNDK version
2. **Safety check** → validate bootloader unlocked, VNDK compatibility, backup exists
3. **Download** GSI → with progress bar and SHA-256 verification
4. **Reboot** to fastbootd → enter userspace fastboot mode
5. **Flash** → vbmeta (disable verification) → system image (128MB chunks) → wipe → reboot
6. **Verify** → confirm Android version and security patch after boot

### Safety Features (Lessons from Real Failures)

This tool was born from a real incident where a Moto G71 5G was bricked during a flash attempt. Every safety feature encodes a lesson learned:

| Safety Check | What It Prevents |
|-------------|-----------------|
| VNDK compatibility validation | Flashing QPR2+ GSI on VNDK 30 devices (causes boot loop) |
| Boot image origin check | Flashing boot.img from a different ROM (kernel mismatch) |
| Pre-flash backup enforcement | Losing the original boot.img with no way to recover |
| USB connection monitoring | Cable disconnect during flash (partial write = brick) |
| Destructive operation confirmation | Accidental data wipe |

## Project Structure

```
phonectl/
├── __init__.py
├── __main__.py              # python -m phonectl entry point
├── cli.py                   # Click CLI commands
├── tui.py                   # Rich interactive TUI
├── core/
│   ├── adb.py               # ADB subprocess wrapper
│   ├── fastboot.py          # Fastboot subprocess wrapper
│   ├── device.py            # Device detection and management
│   ├── safety.py            # Pre-flash safety checks and validation
│   └── backup.py            # Backup/restore boot partitions
├── vendors/
│   ├── base.py              # BaseVendorPlugin abstract class
│   ├── motorola.py          # Motorola reference plugin
│   ├── google.py            # Google Pixel plugin (stub)
│   └── samsung.py           # Samsung plugin (stub)
├── firmware/
│   ├── gsi.py               # GSI version listing and compatibility
│   ├── sources.py           # Firmware source registry (lolinet, Google CDN)
│   └── downloader.py        # Download with progress bar and checksum
└── config/
    ├── vendors.yaml          # Vendor detection rules (USB IDs, properties)
    └── gsi_versions.yaml     # GSI compatibility matrix
```

## Contributing

### Adding a New Vendor Plugin

1. Create `phonectl/vendors/yourvendor.py`
2. Implement the `BaseVendorPlugin` abstract class (see `vendors/base.py`)
3. Register the plugin in `cli.py` → `_create_device_manager()`
4. Add detection rules to `config/vendors.yaml`

### Adding GSI Versions

Edit `phonectl/config/gsi_versions.yaml` to add new GSI builds with their download URLs, checksums, and VNDK compatibility info.

## Documentation

- [Moto G71 5G GSI Flash Guide](docs/Moto_G71_5G_GSI_Flash_Guide.md) — Real-world reference from the session that inspired this tool

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `adb devices` shows empty | Enable USB debugging, replug cable, try `adb kill-server && adb start-server` |
| `adb devices` shows `unauthorized` | Approve the USB debugging prompt on your phone |
| `fastboot devices` shows empty | Motorola quirk — use fastbootd mode instead of low-level bootloader. Replug cable. |
| `pip install` fails with `externally-managed-environment` | Use a virtual environment: `python3 -m venv .venv && source .venv/bin/activate` |
| Phone stuck at boot logo | Enter fastbootd, run `phonectl recover --codename <your-device>` |
| `phonectl info` shows wrong vendor | Device running GSI reports manufacturer as "Google" — detection falls back to codename matching |

## License

Apache License 2.0
