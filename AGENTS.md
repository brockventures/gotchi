# AGENTS.md — Autonomous Agent Operating Guide (`gotchi`)

This repository is co-maintained by human engineers (**Mike / Arbiter**, **Ryan**) and autonomous peer agents (**Amos**, **Zero**).

## 1. Agent Bootstrap & Device Provisioning
- When configuring a physical GOTCHI / SPRITE unit over USB-C (`/dev/ttyACM*` or `/dev/cu.usbmodem*`) or HTTP:
  1. Query `{"cmd": "get_config", "schema": true}` first to inspect the active firmware version, partition slot (`ota_0` / `ota_1`), and supported keys.
  2. Apply changes via `set_config` / `set_wifi` and run `{"cmd": "self_test"}` to verify mic, camera, speaker, and e-paper health before declaring provisioning complete.
  3. Never echo Wi-Fi passwords, per-device bearer tokens, or private endpoint keys into Discord channels or commit history.

## 2. Repository Hygiene & Security
- Keep all hardware pin maps, 3D enclosure CAD/STL files, firmware source, and JSON schema specs documented in version control.
- Never hardcode personal Wi-Fi SSIDs, passwords, LAN IPs (`192.168.x.x` outside standard `192.168.4.1` soft-AP defaults), or bearer tokens in source files.
