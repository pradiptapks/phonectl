# phonectl — Full CLI Reference

Complete command reference for all phonectl commands and options.

> Tip: Run `phonectl <command> --help` for built-in usage information.

---

## Global Options

| Option | Description |
|--------|-------------|
| `--version` | Show version and exit |
| `--help` | Show help message and exit |

---

## Smart Diagnostics

### `phonectl diagnose`

Run smart diagnostics — analyzes device health by collecting evidence from all modules (info, audit, security, storage, tune) and evaluating diagnostic rules. Produces a prioritized action plan with specific `phonectl` commands to fix each issue.

### `phonectl report`

Generate a comprehensive device health report combining all module outputs into a single assessment.

| Option | Description |
|--------|-------------|
| `--export md` | Export report as Markdown file |
| `--export json` | Export report as JSON |
| `--output <path>` | Custom output file path |

---

## Device & Compatibility

### `phonectl info`

Show connected device information — model, Android version, VNDK, RAM, storage, kernel, GPU, battery.

### `phonectl check`

Run 14 hardware/firmware compatibility checks and show ranked GSI recommendations.

| Option | Description |
|--------|-------------|
| `--version <build_id>` | Check compatibility against a specific GSI version |

### `phonectl recommend`

Score and rank all available GSI versions (Android 11–17) against your device hardware. Shows RECOMMENDED, COMPATIBLE, INCOMPATIBLE, or BROKEN verdict with reasons for each.

---

## Security Audit

### `phonectl audit`

Run security audit — warranty estimation, stalkerware scan (150+ signatures), permissions audit, OS integrity checks. 17 non-root + 4 root-level checks.

| Option | Description |
|--------|-------------|
| `--deep` | Include root-level deep scan (hosts file, system integrity, kernel modules, hidden processes) |
| `--export md` | Export report as Markdown file |
| `--export json` | Export report as JSON for automation |
| `--output <path>` | Custom output file path for export |

### `phonectl security`

Network and phone security assessment with 23 checks across 3 categories and a score (0–100).

| Option | Description |
|--------|-------------|
| `--network` | Network security checks only (VPN, proxy, DNS, CA certs, ADB exposure) |
| `--lockscreen` | Lock screen and auth checks only (lock type, timeout, biometrics, Smart Lock) |
| `--apps` | App permission security only (verification, overlay, SMS access, notification listeners) |
| `--score` | Output security score only (0–100) — suitable for scripting |
| `--harden` | Auto-fix failed security checks (disable ADB WiFi, enable app verification, etc.) |
| `--dry-run` | Preview hardening changes without applying (combine with `--harden`) |

---

## Performance Tuning

### `phonectl tune`

Show current performance settings, active profile, and available profiles.

| Option | Description |
|--------|-------------|
| `--profile fast` | Animations off, GPU forced — best for older/slow phones |
| `--profile balanced` | Reduced animations, auto GPU — good for daily use |
| `--profile battery` | Reduced animations, aggressive background cleanup — max battery |
| `--profile gaming` | Animations off, GPU forced, background apps killed — gaming sessions |
| `--compile` | Force ART ahead-of-time compilation for ~20% faster app launches |
| `--reset` | Restore original performance settings from backup |

---

## Storage Management

### `phonectl storage show`

Show storage breakdown — total, used, free, app counts (system vs user).

### `phonectl storage cleanup`

Clean up caches, temp files, and leftover APKs.

| Option | Description |
|--------|-------------|
| `--deep` | Deep cleanup — includes log files and system log buffer |
| `--dry-run` | Preview what would be cleaned without acting |

### `phonectl storage bloatware list`

List detected bloatware for the current vendor.

| Option | Description |
|--------|-------------|
| `--vendor <name>` | Filter by vendor (motorola, samsung, google, xiaomi, etc.) |

### `phonectl storage bloatware disable`

Disable detected bloatware. SafetyGuard prevents disabling critical system apps.

| Option | Description |
|--------|-------------|
| `--vendor <name>` | Filter by vendor |
| `--dry-run` | Preview without disabling |

### `phonectl storage bloatware enable`

Re-enable all previously disabled bloatware apps from the undo log.

### `phonectl storage apps`

List all installed user apps.

---

## Factory Reset

### `phonectl reset`

Show available reset options.

| Option | Description |
|--------|-------------|
| `--factory` | Full factory reset via recovery mode (requires typing `RESET` to confirm) |
| `--wipe-data` | Wipe userdata partition via fastboot (requires typing `RESET` to confirm) |
| `--clear-cache` | Clear all app caches — safe, no data loss, no confirmation needed |
| `--app <package>` | Clear data for a specific app (erases login/settings for that app) |

---

## Flash & Firmware

### `phonectl flash gsi`

Download and flash a GSI image. Auto-selects the best compatible version using the recommendation engine.

| Option | Description |
|--------|-------------|
| `--version <build_id>` | Flash a specific GSI version (blocks incompatible versions with warning) |
| `--no-wipe` | Skip data wipe — for same-major-version security patch updates |

### `phonectl flash stock`

Find stock firmware download URL for the device from lolinet mirrors.

| Option | Description |
|--------|-------------|
| `--codename <name>` | Device codename (auto-detected if omitted) |
| `--region <code>` | Firmware region (default: RETIN for India) |

### `phonectl update`

Update GSI security patch without data loss. Equivalent to `phonectl flash gsi --no-wipe`.

| Option | Description |
|--------|-------------|
| `--version <build_id>` | Target GSI build ID |

### `phonectl firmware list`

List all available GSI versions with compatibility info, security patch dates, and status.

### `phonectl firmware download <build_id>`

Download a specific GSI version for offline use.

### `phonectl firmware regions <codename>`

List available firmware regions for a device from lolinet mirrors.

---

## Backup & Recovery

### `phonectl backup create`

Create a backup of boot partition images.

| Option | Description |
|--------|-------------|
| `--from-dir <path>` | Directory containing boot.img, vendor_boot.img, dtbo.img, vbmeta.img |
| `--codename <name>` | Device codename (auto-detected if omitted) |

### `phonectl backup list`

List all saved backups.

| Option | Description |
|--------|-------------|
| `--codename <name>` | Filter by device codename |

### `phonectl backup restore <path>`

Restore boot partitions from a backup directory. Device must be in fastbootd mode.

### `phonectl recover`

Smart recovery — restore boot partitions with correct vbmeta selection. Reads flash state to determine whether to use GSI or stock vbmeta. Auto-flashes system from GSI cache if available. Includes post-flash boot verification.

| Option | Description |
|--------|-------------|
| `--backup-path <path>` | Specific backup directory to restore from |
| `--codename <name>` | Device codename (for auto-finding backup) |
| `--no-system` | Skip system flash (boot partitions only) |
| `--no-verify` | Skip post-flash boot verification |

---

## Interactive Mode

### `phonectl tui`

Launch the interactive TUI (Terminal User Interface) with a menu-driven interface covering all features.

---

## Future: AI-Powered Commands (Not Yet Implemented)

These commands are planned for future releases via the AI plugin system (`phonectl/ai/`):

### `phonectl ask "<question>"` (future)

AI-powered troubleshooting. Sends device context to Ollama (local) or Claude (MCP) and returns analysis. Falls back to rule-based diagnostics if no AI provider is available.

### `phonectl compat` (future)

Look up community compatibility data for the current device from a crowdsourced database.

### `phonectl compat --submit` (future)

Submit an anonymous compatibility report (codename, VNDK, kernel, GSI build, result only — no PII).

---

## Examples

```bash
# Typical first-time workflow for an out-of-warranty device:
phonectl diagnose                      # 1. Smart diagnostics + action plan
phonectl report                        # 2. Full health assessment
phonectl check                         # 3. Hardware compatibility + GSI recommendations
phonectl backup create --from-dir ./fw # 4. Backup boot partitions
phonectl flash gsi                     # 5. Flash recommended GSI

# Security hardening:
phonectl security                      # Review security posture
phonectl security --harden --dry-run   # Preview fixes
phonectl security --harden             # Apply fixes

# Performance optimization:
phonectl tune --profile fast           # Speed up an old phone
phonectl storage cleanup               # Clear caches
phonectl storage bloatware disable     # Remove bloatware

# Emergency recovery:
phonectl recover --codename corfur     # Restore from backup
```
