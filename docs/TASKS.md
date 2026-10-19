# GOTCHI / SPRITE — V1 Engineering Task Board

Tracked across **Ryan**, **Mike (Arbiter)**, **Amos**, and **Zero**. Status markers: `[ ]` Todo · `[~]` In Progress · `[x]` Done.

---

## Epic 1: Architecture, Spec & Procurement (Milestone M0)
- [x] **T1.1 — Lock V1 Hardware BOM & Pinout Allocation** (`Zero`, `Amos`, `Ryan`, `Mike`)
  - Locked 7-item single-unit shopping list in [`docs/BOM.md`](BOM.md) (`$62.32` Seeed+Waveshare+Amazon / `$70.32` Seeed+Amazon / `$80.32` All-Amazon): `XIAO ESP32S3 Sense` (with included stock camera & PDM mic; `OV5640` AF optional) + `Waveshare 1.54" E-Paper Module V2` (`SKU 12955` / `B0728BJTZC` w/ direct 8-pin PH2.0 harness, replacing discontinued Seeed breakout) + `MAX98357A` I2S amp + `1W 8Ω` cavity speaker + `803040` 1000mAh LiPo + `6x6x5mm` tactile buttons + mini SPDT slide switch.
- [x] **T1.2 — Audit Mirrormere Hub Voice Contract** (`Amos`)
  - Verified `POST /api/voice/interact` (`16 kHz` mono PCM WAV -> SSE stream) in `repos/mirrormere/api/openapi.yaml` and documented in [`docs/MIRRORMERE_VOICE_CLIENT.md`](MIRRORMERE_VOICE_CLIENT.md).
- [ ] **T1.3 — Order V1 Bench Hardware Parts** (`Ryan`, `Mike`)
  - Order 1-unit BOM cart from [`docs/BOM.md`](BOM.md).

---

## Epic 2: ESP32-S3 Core Firmware (`firmware/`) (Milestone M1)
- [x] **T2.1 — Scaffold PlatformIO Project & Dual-OTA Partition Table** (`Zero`)
  - Configure `platformio.ini` for `seeed_xiao_esp32s3` with 8MB Flash (`ota_0`, `ota_1`, `nvs`, `coredump`) and 8MB Octal PSRAM enabled.
- [x] **T2.2 — Implement Dual-Transport JSON-RPC Config & `self_test` Engine** (`Zero`, `Amos`)
  - Shared command dispatcher over USB-C CDC Serial (`115200`) and Wi-Fi HTTP (`get_config`, `set_config`, `set_wifi`, `self_test`, `get_logs`, `reboot`, `factory_reset`).
- [x] **T2.3 — PDM Microphone Capture & PSRAM WAV Ring Buffer** (`Zero`)
  - Configure I2S/PDM RX on `GPIO41` (`CLK`) and `GPIO42` (`DATA`) at `16 kHz` 16-bit mono; buffer PTT recordings in PSRAM with a 500ms circular pre-roll.
- [x] **T2.4 — `MAX98357A` I2S Audio Output & Chime/TTS Stream Player** (`Zero`)
  - Configure I2S TX on `D7` (`GPIO44` BCLK — silent at boot), `D6` (`GPIO43` LRCLK), and `D9` (`GPIO8` DIN) to play streamed TTS audio chunks (`24 kHz` default from Mirrormere SSE) and Tamagotchi UI chimes.
- [x] **T2.5 — Camera Driver (`OV2640`/`OV3660` Stock Baseline + Optional `OV5640` AF)** (`Zero`)
  - Auto-detect attached DVP sensor on boot (`OV2640`/`OV3660` stock baseline out of the box; enable `0x3022 = 0x08` single-shot VCM autofocus when `OV5640` is present) and expose JPEG snapshot capture for multimodal prompts.
- [x] **T2.6 — Waveshare 1.54" E-Paper V2 (`SSD1681`) Sprite & Partial-Refresh Renderer** (`Amos`, `Zero`)
  - [x] Audited `client/eink-node/` in Mirrormere (`Amos` in [`docs/MIRRORMERE_VOICE_CLIENT.md`](MIRRORMERE_VOICE_CLIENT.md) / PR #1).
  - [x] Configure `GxEPD2` (`GxEPD2_154_D67` / `SSD1681`, `200x200`, 2 gray levels B/W, `0.3s` partial / `2.0s` full refresh) on direct 8-pin harness pins `D0/D1/D3/D5/D8/D10` with bounded `BUSY` timeout (`30s`) and `PanelManager.write_frame` full-refresh recovery policy.
  - Firmware renderer: PR #5 (GOTCHI firmware T2.6: e-paper renderer and refresh policy (C++), plus AGENTS.md pin fixes)
- [x] **T2.7 — QR Soft-AP Captive Portal Onboarding (`192.168.4.1`)** (`Zero`)
  - Render scannable Wi-Fi QR code on the 200x200 e-paper screen when unprovisioned; serve mobile captive portal to set Wi-Fi and hub URL without an on-screen keyboard.

---

## Epic 3: Backend Integration & Remote Auth (`backend/`) (Milestone M2)
- [~] **T3.1 — Mirrormere `/api/voice/interact` Device Client Spec & SSE Parser** (`Amos`, `Zero`)
  - [x] Documented wire spec in [`docs/MIRRORMERE_VOICE_CLIENT.md`](MIRRORMERE_VOICE_CLIENT.md) (PR #1): multipart WAV upload, SSE events (`state`, `transcript`, `status`, `thinking`, `reply`, `audio_chunk` at `24 kHz` default base64 PCM, `error`, `done`), and `400`/`409`/`500`/`503` handling (sprite state derived on-device from `state` events).
  - [x] Implement device multipart WAV client, SSE stream parser, and Pi Zero W POC harness (`poc/gotchi_poc.py`, `firmware/`).
  - Firmware client: PR #8 (T3.1 firmware, the Mirrormere voice client), PTT to upload to SSE to playback. Not flashed, not hardware-tested.
- [ ] **T3.2 — Per-Device Bearer Token Auth & Remote Tunnel Gateway** (`Amos`, `Zero`)
  - Add bearer token verification middleware for off-LAN requests arriving from mobile hotspots or the Android BLE-to-Tailscale forwarder.
- [ ] **T3.3 — Discord Voice / Headphone Audio Routing Mode** (`Zero`, `Amos`)
  - Support `audio_out_mode: "speaker" | "discord_voice" | "ble_phone"` so Mike and Ryan can receive voice replies straight in AirPods/Pixel Buds when desired.

---

## Epic 4: Headless Android BLE-to-Tailscale Forwarder (`android-ble-forwarder/`) (Milestone M3)
- [ ] **T4.1 — Define BLE GATT / L2CAP CoC Framing Protocol** (`Zero`)
  - Specify packet framing for streaming PTT audio chunks, JPEG snapshots, and SSE return events over BLE 5.0 (`2M PHY`).
- [ ] **T4.2 — Build Headless Android Foreground Service** (`Zero`)
  - Lightweight Kotlin app/service for Ryan's Pixel that auto-bonds to GOTCHI over BLE in the background and forwards requests over Tailscale to Mirrormere/Discord.

---

## Epic 5: Multi-Part 3D-Printed Enclosure & Future Wake Models (Milestone M4)
- [x] **T5.1 — Multi-Part Openable 3D-Printed Pocket Case (`cad/`)** (`Amos`, `Zero`, `Ryan`)
  - Model a multi-part openable enclosure in Blender / CAD sized to the locked 7-item mechanical envelope in [`docs/HARDWARE_ASSEMBLY.md`](HARDWARE_ASSEMBLY.md): Waveshare `48.0 x 33.0 mm` e-paper V2 module (`27.6 x 27.6 mm` bezel window + 4x `M2` bosses), stacked XIAO ESP32S3 Sense (`21.0 x 17.8 x 15.0 mm` w/ `USB-C` + camera/mic apertures), `803040` `40 x 30 x 8 mm` LiPo bay, `MAX98357A` + `1W 8Ω` cavity speaker grille, 2x `6x6x5mm` tactile button actuators, and recessed SPDT slide switch slot.
- [ ] **T5.2 — V1.1 Wake-Word & Tiny Audio-Intent Classifier Spike** (`Mike`, `Zero`, `Amos`)
  - Benchmark `microWakeWord` / `ESP-SR` and Mike's wake-word-free tiny audio-intent classifier on the ESP32-S3 vector unit (`ESP-NN`), measuring real-world mA draw against the 1000 mAh LiPo.
