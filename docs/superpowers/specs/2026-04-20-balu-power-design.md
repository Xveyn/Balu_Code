# BaluPower — Intelligent GPU Power Management Design

**Status:** draft, user-approved
**Date:** 2026-04-20
**Scope:** new sub-package `power/` alongside `plugin/`, `cli/`, `shared/` in the Balu_Code monorepo
**Hardware target (v1):** AMD RX 7900 XT / XTX (RDNA3) on Linux with `amdgpu` driver
**Language/stack:** Python 3.12+, `asyncio`, systemd (consistent with rest of repo)

## §1 — Architecture & Scope

BaluPower is a privileged system daemon that arbitrates GPU power states from multiple trigger sources. It is **not** part of the Balu Code coding-agent plugin — it lives in the same monorepo for convenience, but is installed and runs independently. Balu Code does not depend on it and vice versa.

**Problem:** an RX 7900 XT in a workstation pulls measurable idle and peak power. Different workloads benefit from different GPU profiles (gaming needs 3D_FULL_SCREEN; LLM inference needs COMPUTE; desktop idle should use POWER_SAVING; display-off can drop to DPM floor). Switching these profiles manually is tedious, and consumer tools (CoreCtrl, LACT) assume a single human operator, not multiple automated workloads.

**Design axis:** *push-only* daemon + small, single-responsibility clients. Daemon receives claims from clients, resolves conflicts by priority, writes sysfs. No polling inside the daemon.

### Components

```
                   ┌─────────────────────────────────────────┐
                   │  balu-power daemon (root, systemd)      │
                   │   Unix socket listener (NDJSON)         │  /run/balu-power.sock
                   │   Claim registry (TTL + priority)       │  group: balu-power, 0660
                   │   GPU driver (sysfs writer)             │  /sys/class/drm/card*/…
                   │   Audit log (journald)                  │
                   └────────────▲────────────────────────────┘
                                │ Unix socket (NDJSON)
    ┌───────────────────────────┼───────────────────────────┐
    │                           │                           │
┌───┴──────────┐         ┌──────┴─────────┐          ┌──────┴──────────┐
│ balu-powerctl│         │ ollama-watcher │          │ GameMode hook   │
│ (user CLI)   │         │ (user systemd) │          │ (shell script)  │
└──────────────┘         └────────────────┘          └─────────────────┘
                                                     ┌─────────────────┐
                                                     │ display-watcher │
                                                     │ (user systemd,  │
                                                     │  logind DBus)   │
                                                     └─────────────────┘
```

### Repo layout

```
Balu_Code/
├── plugin/                    (existing coding-agent)
├── cli/                       (existing)
├── shared/                    (existing)
├── power/                     ← NEW, independent sub-package
│   ├── balu_power/
│   │   ├── __init__.py
│   │   ├── daemon.py          # asyncio entry + socket loop
│   │   ├── registry.py        # claim/release/TTL/priority resolution
│   │   ├── gpu_driver.py      # sysfs writer, idempotent
│   │   ├── protocol.py        # NDJSON request/response schema
│   │   ├── profiles.py        # profile definitions + yaml loader
│   │   └── hw_detect.py       # AMD RDNA3 detection
│   ├── balu_powerctl/
│   │   └── __main__.py        # CLI wrapper over the socket
│   ├── watchers/
│   │   ├── ollama_watcher.py  # polls /api/ps
│   │   └── display_watcher.py # subscribes logind IdleHint
│   ├── contrib/
│   │   ├── gamemode-hook.ini  # example custom gamemode.ini
│   │   └── systemd/
│   │       ├── balu-power.service
│   │       ├── balu-power-ollama-watcher.service     (user unit)
│   │       └── balu-power-display-watcher.service    (user unit)
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── live/              # manual hardware smoke-tests
│   └── pyproject.toml
└── docs/
    └── power/
        ├── setup.md           # install, group membership, systemd
        ├── configuration.md   # profiles.yaml + overrides
        └── clients.md         # how to write your own trigger client
```

### Out of scope for v1

- Non-AMD GPUs (NVIDIA `nvidia-smi`, Intel `intel_gpu_top`). Stays YAGNI — yaml override exists for users who want to hack it.
- Per-process GPU tracking (cgroup-style) — the daemon operates on a whole card, not per-workload attribution.
- Policy engine / scheduling (e.g. "LLM yields GPU to gaming with grace period"). Priority resolution is enough.
- GUI / tray app. CLI + journald is the v1 UX.
- Balu Code integration hook (direct push from `agent_loop.py`). Ollama-watcher covers this transparently. Can be added later as a Phase 5+ enhancement if latency matters.

## §2 — Profiles & Priority

Five profile states, resolved by `max(priority)` over active claims.

| Profile | Priority | `power_dpm_force_performance_level` | `pp_power_profile_mode` | `power1_cap` | Trigger source |
|---|---|---|---|---|---|
| `gaming` | **4** | `auto` | `1` (3D_FULL_SCREEN) | not touched (kernel default 315 W) | GameMode custom hook |
| `compute` | **3** | `auto` | `4` (COMPUTE) | not touched | ollama-watcher (model active) |
| `display-off` | **2** | `low` | `5` (POWER_SAVING) | not touched | display-watcher (logind IdleHint=true) |
| `llm-idle` | **1** | `auto` | `5` (POWER_SAVING) | not touched | ollama-watcher (model loaded, inactive) |
| `idle` | **0** (implicit fallback) | `auto` | `5` (POWER_SAVING) | not touched | daemon default when registry empty |

### Semantics

- **Watchers push only positive signals.** They never push `idle`. An empty registry implicitly means `idle`.
- **Daemon default** on startup and on empty registry is `idle`. No persistence across restarts — registry is RAM-only by design.
- `power1_cap` is **not set** by the daemon in v1 unless explicitly configured in `profiles.yaml`. Rationale: the RX 7900 XT TDP is 300 W, default kernel cap is 315 W, idle draw is ~15–30 W (already well under the cap). A cap only matters if the user wants to hard-limit peak draw; that is their opt-in.
- **`display-off` and `compute` are orthogonal**: `compute + display-off` in the registry resolves to `compute` (priority 3 > 2). This preserves the "Ollama generates while user is away / TV off" use case. When `compute` expires, daemon falls back to `display-off` until the display returns.

### Profile config override

`/etc/balu-power/profiles.yaml` (optional; if absent, hardcoded defaults apply):

```yaml
profiles:
  gaming:
    performance_level: auto
    power_profile_mode: 1
    # power_cap_w: 280     # optional, not set by default
  compute:
    performance_level: auto
    power_profile_mode: 4
  display-off:
    performance_level: low
    power_profile_mode: 5
  llm-idle:
    performance_level: auto
    power_profile_mode: 5
    # ollama_unload: false # optional, see §3
  idle:
    performance_level: auto
    power_profile_mode: 5

# Priority, low to high. Daemon resolves max() of active claims using this ordering.
priority: [idle, llm-idle, display-off, compute, gaming]

# Hardware targeting. Auto-detected if omitted.
card: card0
```

### Safe-defaults guard

A non-overridable file `/etc/balu-power/safe-defaults.conf` (shipped with the package) defines hard never-exceed bounds:

```ini
[limits]
max_power_cap_w = 400
allowed_performance_levels = auto,low,high,profile_standard,profile_min_sclk,profile_min_mclk,profile_peak
```

If a user-yaml profile exceeds these, daemon rejects the config at startup with `ERROR` in journald and exits. Prevents a copy-pasted bad yaml from cooking the GPU.

## §3 — Protocol

Transport is a Unix Domain Socket at `/run/balu-power.sock`, owner `root:balu-power`, mode `0660`. Users must be in group `balu-power` to send messages.

Wire format is newline-delimited JSON (NDJSON). One request per line, one response per line. Max 4 KiB per line (DoS guard); connections exceeding this are closed.

### Requests

```jsonc
// Claim — client registers a state it wants active.
{"v": 1, "op": "claim", "client_id": "ollama-watcher", "state": "compute", "ttl_seconds": 15}

// TTL semantics:
//   positive integer : expires after N seconds; client must refresh (heartbeat)
//   null             : holds until explicit release (for GameMode on_start, display-off)
//   0 or negative    : rejected with "invalid_ttl"

// Release — client withdraws its claim.
{"v": 1, "op": "release", "client_id": "ollama-watcher"}

// Status — introspection (read current state + all active claims).
{"v": 1, "op": "status"}

// Reload — re-read /etc/balu-power/profiles.yaml without restart.
{"v": 1, "op": "reload"}
```

### Responses

```jsonc
// Success (claim/release/reload)
{"ok": true}

// Status response
{"ok": true,
 "current_state": "compute",
 "claims": [
   {"client_id": "ollama-watcher", "state": "compute", "expires_in_s": 12},
   {"client_id": "display-watcher", "state": "display-off", "expires_in_s": null}
 ]}

// Error
{"ok": false, "error": "unknown_state", "message": "state 'turbo' not in profiles"}
```

### Claim semantics

- `client_id` is chosen by the client and must be stable per client instance (`"ollama-watcher"`, `"display-watcher"`, `"gamemode"`, `"manual"`). Daemon does not validate format; collisions are the user's responsibility.
- A second `claim` with the same `client_id` **replaces** the first. At most one claim per `client_id` in the registry.
- Multiple different `client_id`s coexist → this is the `compute + display-off` coexistence case.
- **Reconciler is idempotent**: on every claim/release/TTL-expiry event, it computes the target profile (`max(priority)`) and writes sysfs **only if it differs from the last-written profile**. Prevents flap-writes.

### Manual override (CLI)

`balu-powerctl` is a thin wrapper producing normal claims with `client_id="manual"`:

```bash
balu-powerctl claim gaming              # claim with ttl=null
balu-powerctl claim compute --ttl 60    # claim with 60s ttl
balu-powerctl release                   # release the "manual" claim
balu-powerctl status                    # JSON status pretty-printed
```

No special privilege handling. If the user wants to *force* `idle` while other clients are active, they must release those clients manually (e.g. `systemctl --user stop balu-power-ollama-watcher.service`). This is acceptable v1 behavior; a `force` flag can come later.

### Example sequence (Ollama generating while TV is off)

```
display-watcher → {"op":"claim","client_id":"display-watcher","state":"display-off","ttl_seconds":null}
                ← {"ok":true}
                [registry: display-off(∞) → reconciler writes display-off profile]

ollama-watcher  → {"op":"claim","client_id":"ollama-watcher","state":"compute","ttl_seconds":15}
                ← {"ok":true}
                [registry: display-off(∞), compute(15s) → max=compute → reconciler writes compute]

[10s later, watcher refreshes]
ollama-watcher  → {"op":"claim","client_id":"ollama-watcher","state":"compute","ttl_seconds":15}
                ← {"ok":true}
                [no delta — no sysfs write]

[generation ends; watcher sees no active model; lets TTL expire by not refreshing]
                [registry: display-off(∞) → max=display-off → reconciler writes display-off]

[user returns; compositor sets IdleHint=false]
display-watcher → {"op":"release","client_id":"display-watcher"}
                ← {"ok":true}
                [registry empty → reconciler writes idle (implicit fallback)]
```

### `llm-idle` Ollama unload — config-gated

An optional behavior controlled by `profiles.llm-idle.ollama_unload: true` in yaml:

- When the ollama-watcher transitions a model from active to merely-loaded, it additionally posts `{"model": "<name>", "keep_alive": 0}` to Ollama's `/api/generate` to evict the model from VRAM.
- **Default: false.** Rationale: eviction saves ~30–50 W but imposes a 2–5 s cold-start cost on the next prompt (14B q4 on 7900 XT). Sven's usage pattern (active dev loop) makes cold-start-every-time more painful than the power savings are worth. Power users can flip it on in yaml.

## §4 — Security, Privileges, Failsafes

### Daemon privilege model

- **Daemon** runs as root. sysfs writes on `/sys/class/drm/card*/device/` require it; setuid helpers would add complexity without meaningful attack-surface reduction (the daemon is the privileged write path regardless).
- **Socket ACL**: `/run/balu-power.sock` is `root:balu-power 0660`. Group `balu-power` is created by the postinstall step. Users add themselves via `sudo usermod -aG balu-power $USER`.
- **No polkit**. Follows Docker/libvirt group convention; simpler, matches user expectations.

### systemd hardening

```ini
# /lib/systemd/system/balu-power.service
[Service]
ExecStart=/usr/bin/balu-power
ExecStopPost=/usr/libexec/balu-power-reset
Restart=on-failure
RestartSec=2
StartLimitBurst=3
StartLimitIntervalSec=60

ProtectSystem=strict
ReadWritePaths=/sys/class/drm /sys/class/hwmon /run
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_DAC_OVERRIDE
RestrictAddressFamilies=AF_UNIX
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
```

### Non-root components

- **ollama-watcher** and **display-watcher** run as user systemd units (`systemctl --user`). They need only group-`balu-power` membership to write to the socket.
- **GameMode hook** is a shell script invoked by GameMode itself (which runs as the user). Example `~/.config/gamemode.ini`:

  ```ini
  [custom]
  start=/usr/bin/balu-powerctl claim gaming
  end=/usr/bin/balu-powerctl release
  ```

### Input validation

| Condition | Response |
|---|---|
| JSON parse error | `{"ok":false,"error":"parse_error"}`, connection stays open |
| Unknown `op` | `unknown_op` |
| Unknown `state` (not in loaded profiles.yaml) | `unknown_state` |
| `ttl_seconds <= 0` (except `null`) | `invalid_ttl` |
| Missing required field | `missing_field` |
| Line > 4 KiB | connection closed, log WARN |

### sysfs write failures

- **Write EIO / EBUSY** (known RDNA3 quirks on some kernels): log WARN in journald, leave last-written profile in effect, keep the claim in the registry. Retry on next reconcile tick.
- **Sysfs path missing** (wrong card, GPU hot-plug): ERROR on startup → daemon refuses to start, systemd shows failed status. Manual intervention required.
- **No catch-all exception suppression**. Let unexpected exceptions crash the daemon; systemd restarts.

### Failsafes on crash / stop

1. `systemd Restart=on-failure, RestartSec=2s, StartLimitBurst=3/60s` — auto-restart up to 3 times per minute, then give up to prevent boot-loops.
2. `ExecStopPost=/usr/libexec/balu-power-reset` runs *always* on stop/crash. It writes `auto` + `profile=0` (BOOTUP_DEFAULT) to sysfs unconditionally. Does not read state; always resets to kernel defaults.
3. If the reset hook itself fails, the GPU retains whatever profile was last written. Not dangerous (kernel enforces its own bounds), but may leave the card in gaming profile during idle until next boot or manual `balu-powerctl claim idle`.
4. `safe-defaults.conf` prevents config-driven over-draw regardless of daemon state.

### Audit

All profile transitions log to journald:

```
balu-power: transition idle → compute (trigger: claim from ollama-watcher, ttl=15s)
balu-power: transition compute → display-off (trigger: claim expired for client_id=ollama-watcher)
balu-power: ERROR sysfs write failed: /sys/class/drm/card0/device/pp_power_profile_mode: EIO; retaining previous profile
```

Queryable via `journalctl -u balu-power`. No separate log file.

### Hardware detection

On startup, `hw_detect.py` walks `/sys/class/drm/card*/device/`:
- Vendor `0x1002` (AMD) required.
- Device ID matched against a shipped allowlist of known-good RDNA3 IDs (7900 XT, 7900 XTX, 7900 GRE, 7800 XT, 7700 XT).
- Unknown AMD device → log WARN `"untested hardware, proceeding with generic sysfs paths"` and continue.
- No AMD device → log ERROR and exit. (Use case: accidental install on Intel-only system.)
- Multi-GPU: pick first matching card unless yaml `card:` overrides.

## §5 — Test Strategy

### Unit tests (`power/tests/unit/`, pytest)

- **`test_registry.py`** — claim/release/TTL-expiry, priority resolution, duplicate-`client_id` replacement, empty-registry fallback to `idle`.
- **`test_protocol.py`** — JSON parser, validation branches (unknown_op, invalid_ttl, missing_field), 4 KiB line-size guard.
- **`test_gpu_driver.py`** — sysfs writer against `tmp_path` (simulates `/sys/class/drm/…` as a tmpfs tree). Verifies: idempotent writes (no write on delta=0), correct value per profile, graceful behavior on write-error (EIO simulated by read-only file).
- **`test_profiles.py`** — yaml loader, defaults merge, safe-defaults-guard rejects `power_cap_w: 500`, rejects invalid `performance_level`.
- **`test_hw_detect.py`** — walks a mocked `/sys/class/drm/` tree, picks correct card, handles multi-GPU with yaml override.

### Integration tests (`power/tests/integration/`)

- **Daemon roundtrip** — starts real daemon process against tmpfs-mocked sysfs, exercises full claim/release via actual Unix socket, asserts final sysfs state. SIGTERM → asserts reset-hook fired.
- **Conflict scenario** — claim `compute` + claim `display-off` concurrently → current_state must be `compute`; release `compute` → switches to `display-off`; release `display-off` → falls back to `idle`.
- **Ollama-watcher** — spins up an `http.server` mock for `/api/ps` returning a scripted sequence (active model → loaded-but-idle model → no models), runs the real watcher against a mock daemon, asserts the expected claim/release sequence.
- **Display-watcher** — uses `python-dbusmock` to simulate `org.freedesktop.login1` IdleHint transitions, asserts claim/release.

### Live verification (`power/tests/live/`, manual, NOT in CI)

- `verify_7900xt.sh` — runs on real hardware, exercises each profile via `balu-powerctl`, reads back `power_dpm_force_performance_level` / `pp_power_profile_mode` from sysfs, compares to expected values. Documented in `docs/power/verification.md` as a pre-release smoke-test.

### CI

- GitHub Actions, matrix Python 3.12 / 3.13, `ubuntu-latest`.
- Unit + integration tests run in the container; sysfs is fully mocked via `tmp_path`, DBus via `python-dbusmock`.
- Coverage target: ≥ 85 % on `power/balu_power/`.

### Not automated (accepted gaps)

- Actual GPU behavior under load — no way to test without hardware.
- Two-line GameMode shell hook — visual review.
- Full systemd-unit semantics — no substitute for `systemctl start` on prod.

### Manual verification flow (parallel to existing `docs/phase-*-verification.md`)

Documented as `docs/power-phase-1-verification.md`:

1. Install via `scripts/install-balu-power.sh`.
2. `balu-powerctl status` → current_state=`idle`, claims=[].
3. Run Ollama prompt → `journalctl -u balu-power` shows transition to `compute`.
4. Force monitor off (`xset dpms force off` on X11; compositor-specific on Wayland) → transition to `display-off`.
5. Start Steam/Proton game → transition to `gaming`.
6. Confirm each transition with `radeontop` / `nvtop` visual match (GFX clock, power profile indicator).
7. Kill daemon (`systemctl stop balu-power`) → sysfs values reset to kernel defaults.
