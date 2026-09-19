# tuya-telegram-control

Control Tuya smart devices from the Tuya Cloud API, with the eventual goal of
driving them from Telegram (either a standalone bot or a tool exposed to the
existing Jarvis/OpenClaw agent).

Right now this repo contains the **CLI + manager layer** — the part that talks
to Tuya. The Telegram layer is not built yet; see [Status](#status).

## Layout

| Path | What it is |
| --- | --- |
| `scripts/tuya_manager.py` | `TuyaDeviceManager` — the importable API wrapper (devices, status, control, scenes, automations) |
| `scripts/tuya-cli.py` | `argparse` CLI over the manager, for testing and shell use |
| `config.env.example` | Template for credentials — copy to `config.env` (gitignored) |
| `Dockerfile` / `docker-compose.yml` | Long-running idle container you `docker exec` commands into |

## Setup

### 1. Whitelist the host's outbound IP on Tuya

Tuya rejects API calls from non-allowlisted IPs when the allowlist is enabled.

```bash
curl -4 ifconfig.me   # run on the machine that will make the calls
```

Then: platform.tuya.com → Cloud → your project → Overview → **Cloud
Authorization IP Allowlist** → toggle on → Configure → pick the tab for your
data center → **+ Add IP**. One-time step per host.

### 2. Credentials

```bash
cp config.env.example config.env
$EDITOR config.env
```

Fill in `TUYA_ACCESS_ID`, `TUYA_ACCESS_SECRET`, `TUYA_UID` and
`TUYA_ENDPOINT` (see the comments in the file for where each comes from).
`config.env` is gitignored — keep it that way.

Configuration resolution order is: a `config.env` found in the working
directory or repo root, then environment variables. Under Docker no
`config.env` is copied into the image, so the compose `env_file` supplies
everything as environment variables.

### 3. Run

**Docker:**

```bash
docker compose up -d --build
docker exec -it tuya-control python scripts/tuya-cli.py list
```

**Plain venv:**

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/tuya-cli.py list
```

No inbound ports are needed — the container only makes outbound HTTPS calls to
Tuya, so nothing needs to go through a reverse proxy.

If you rotate the Access Secret on Tuya's platform, update `config.env` and
`docker compose restart`.

## CLI

`python scripts/tuya-cli.py --help` lists everything. The common ones:

Arguments are positional, not flags:

```bash
tuya-cli.py list                              # all devices
tuya-cli.py devices                           # devices for the linked app account
tuya-cli.py find "living room"                # search by name
tuya-cli.py info <device_id>                  # device details
tuya-cli.py device_func <device_id>           # supported functions / DP codes
tuya-cli.py status <device_id>                # current status
tuya-cli.py on  <device_id>                   # turn on  (add -s <code> for a non-default switch)
tuya-cli.py off <device_id>                   # turn off
tuya-cli.py brightness <device_id> 50
tuya-cli.py temperature <device_id> 22
tuya-cli.py set <device_id> <dp_code> <dp_value>
tuya-cli.py batch-on  <id1> <id2> ...
tuya-cli.py batch-off <id1> <id2> ...
```

Families, scenes and automations:

```bash
tuya-cli.py family_list
tuya-cli.py family_devices <home_id>
tuya-cli.py family_rooms   <home_id>
tuya-cli.py scene_list     <home_id>
tuya-cli.py automations    <home_id>
tuya-cli.py automation_on  <home_id> <automation_id>
tuya-cli.py automation_off <home_id> <automation_id>
tuya-cli.py automation_del <home_id> <automation_id>
tuya-cli.py add_automation <home_id> --json-file plan.json
```

`on`/`off` default to the DP code `switch_1`. Devices using a different code
(`switch`, `switch_led`, …) need `on <id> -s switch_led` or
`set <id> <code> <value>` — check `device_func <id>` first.

## Status

- [x] Tuya manager + CLI
- [x] Docker packaging
- [ ] Verify against real devices (`tuya-cli.py list` returning the actual device list)
- [ ] Telegram interface — undecided between a standalone bot and a tool for the
      existing Jarvis/OpenClaw agent. The manager is importable
      (`from scripts.tuya_manager import TuyaDeviceManager`), so either path
      reuses it rather than shelling out to the CLI.
