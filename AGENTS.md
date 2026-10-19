# AGENTS.md — Autonomous Agent Operating Guide (`gotchi`)

This repository is co-maintained by human engineers (**Mike / Arbiter**, **Ryan**) and autonomous peer agents (**Amos**, **Zero**). Any agent operating on this repository or configuring a physical GOTCHI / SPRITE device must follow these contracts.

---

## 1. Project Overview & Repository Layout

- **`README.md`**: High-level project overview, locked V1 hardware baseline, and transport modes.
- **`docs/BOM.md`**: Locked V1 Bill of Materials, exact part numbers, and verified purchase links.
- **`docs/HARDWARE_ASSEMBLY.md`**: Physical pinout allocation table (`D0–D10` + internal Sense pins) and step-by-step meatspace soldering/wiring instructions.
- **`docs/ARCHITECTURE.md`**: System topology, Mirrormere `POST /api/voice/interact` wire specification, BLE-to-Tailscale relay protocol, and JSON-RPC config spec.
- **`docs/TASKS.md`**: Active engineering task board and milestone ownership across **Zero**, **Amos**, **Ryan**, and **Mike**.
- **`firmware/`** *(scaffolded in Milestone M1)*: ESP32-S3 PlatformIO project (`seeed_xiao_esp32s3`).
- **`android-ble-forwarder/`** *(scaffolded in Milestone M3)*: Headless Android BLE-to-Tailscale companion relay service.
- **`cad/`** *(scaffolded in Milestone M4)*: OpenSCAD / STEP files and print-ready STLs for the 3D-printed pocket shell.

---

## 2. Hardware Pinout Invariants (Do Not Violate in Firmware)

When writing or reviewing firmware for the **Seeed Studio XIAO ESP32S3 Sense** stacked on the **Seeed ePaper Breakout Board**:
1. **ePaper SPI Pins (Hardwired by Breakout):**
   - `RST` = `D0` (`GPIO1`), `CS` = `D1` (`GPIO2`), `DC` = `D3` (`GPIO4`), `BUSY` = `D5` (`GPIO6`), `SCK` = `D8` (`GPIO7`), `MOSI` = `D10` (`GPIO9`).
2. **MAX98357A I2S Audio Output Pins:**
   - `BCLK` = `D6` (`GPIO43`), `LRCLK` = `D7` (`GPIO44`), `DIN` = `D9` (`GPIO8`).
   - *Crucial:* Never assign I2S to `D5` (`GPIO6`), as `D5` is hardwired to the ePaper `BUSY` line on the Seeed breakout.
3. **Tactile Buttons & Reserved V2 Wake Pin:**
   - `BTN_TOP` (Push-to-Talk & Deep-Sleep Wake) = `D2` (`GPIO3` / `RTC_GPIO3`, active-low with internal pull-up).
   - `BTN_BOT` (Secondary / Mode / Snap) = `GPIO0` (or removable jumper on `D4` / `GPIO5`).
   - `D4` (`GPIO5` / `RTC_GPIO5`) is reserved as the future hardware wake interrupt / `I2C_SDA` expansion pin.
4. **Internal Sense Expansion Board Pins:**
   - Digital PDM Microphone: `CLK` = `GPIO41`, `DATA` = `GPIO42`.
   - `OV5640` DVP Camera: `GPIO10–18`, `GPIO38–40`, `GPIO47–48`.

---

## 3. Agent Bootstrap & Device Provisioning Protocol

Every GOTCHI unit is **100% agent-configurable** over both **USB-C CDC Serial (`115200` baud)** and **Wi-Fi HTTP (`POST /api/rpc`)** using identical JSON payloads:

1. **Discover Capabilities First:**
   - Send `{"cmd": "get_config", "schema": true}` before mutating settings. Inspect the active firmware version, running partition (`ota_0` or `ota_1`), and self-describing schema.
2. **Provision Network & Hub Target:**
   - Configure Wi-Fi slots via `{"cmd": "set_wifi", "slot": 0, "ssid": "...", "psk": "..."}` (Slot 0 = Home Wi-Fi, Slot 1 = Mobile Hotspot).
   - Configure runtime parameters via `{"cmd": "set_config", "hub_url": "...", "node_id": "...", "wake_mode": "ptt", "audio_out_mode": "speaker"}`.
3. **Mandatory Hardware Verification (`self_test`):**
   - After flashing or reconfiguring a unit, always execute `{"cmd": "self_test"}` and verify passing receipts for all four subsystems (`speaker`, `mic`, `camera`, `display`) before declaring provisioning complete.
4. **Dual-Slot OTA Safety:**
   - OTA updates write to the inactive partition (`ota_0` <-> `ota_1`) and require a clean `self_test` heartbeat within 60 seconds of boot; otherwise the bootloader automatically rolls back to the previous working slot.

---

## 4. Security, Privacy & Collaboration Rules

- **Zero Hardcoded Secrets or Topology:** Never commit personal Wi-Fi SSIDs, passwords, private RFC 1918 LAN IPs (`192.168.x.x` outside the standard `192.168.4.1` soft-AP captive portal default), Tailscale IPs, or bearer tokens to any tracked file.
- **Log Redaction:** Firmware `get_logs` and agent diagnostic outputs must redact `psk` and `bearer_token` fields unconditionally.
- **Multi-Agent Coordination:** Check [`docs/TASKS.md`](docs/TASKS.md) before starting a task, keep PRs scoped and atomic, and update documentation alongside code changes.
