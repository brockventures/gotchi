# GOTCHI / SPRITE — V1 Engineering Task Board

Tracked across **Ryan**, **Mike (Arbiter)**, **Amos**, and **Zero**. Status markers: `[ ]` Todo · `[~]` In Progress · `[x]` Done.

---

## Epic 1: Architecture, Spec & Procurement (Milestone M0)
- [x] **T1.1 — Lock V1 Hardware BOM & Pinout Allocation** (`Zero`, `Amos`, `Ryan`, `Mike`)
  - Locked `XIAO ESP32S3 Sense` + `OV5640` AF camera + `$5 Seeed ePaper Breakout` + `1.54" SSD1681` e-paper + `MAX98357A` I2S amp + `800–1000 mAh LiPo` + 2 tactile buttons + slide switch.
- [x] **T1.2 — Audit Mirrormere Hub Voice Contract** (`Amos`)
  - Verified `POST /api/voice/interact` (`16 kHz` mono PCM WAV -> SSE stream) in `repos/mirrormere/api/openapi.yaml`.
- [ ] **T1.3 — Order V1 Bench Hardware Parts** (`Ryan`, `Mike`)
  - Order BOM items from [`docs/BOM.md`](BOM.md).

---

## Epic 2: ESP32-S3 Core Firmware (`firmware/`) (Milestone M1)
- [ ] **T2.1 — Scaffold PlatformIO Project & Dual-OTA Partition Table** (`Zero`)
  - Configure `platformio.ini` for `seeed_xiao_esp32s3` with 8MB Flash (`ota_0`, `ota_1`, `nvs`, `coredump`) and 8MB Octal PSRAM enabled.
- [ ] **T2.2 — Implement Dual-Transport JSON-RPC Config & `self_test` Engine** (`Zero`, `Amos`)
  - Shared command dispatcher over USB-C CDC Serial (`115200`) and Wi-Fi HTTP (`get_config`, `set_config`, `set_wifi`, `self_test`, `get_logs`, `reboot`, `factory_reset`).
- [ ] **T2.3 — PDM Microphone Capture & PSRAM WAV Ring Buffer** (`Zero`)
  - Configure I2S/PDM RX on `GPIO41` (`CLK`) and `GPIO42` (`DATA`) at `16 kHz` 16-bit mono; buffer PTT recordings in PSRAM with a 500ms circular pre-roll.
- [ ] **T2.4 — `MAX98357A` I2S Audio Output & Chime/TTS Stream Player** (`Zero`)
  - Configure I2S TX on `D6` (`GPIO43` BCLK), `D7` (`GPIO44` LRCLK), and `D9` (`GPIO8` DIN) to play streamed TTS audio chunks and Tamagotchi UI chimes.
- [ ] **T2.5 — `OV5640` Camera Driver & Single-Shot VCM Autofocus** (`Zero`)
  - Initialize DVP camera pins, load `OV5640` AF firmware registers (`0x3022 = 0x08`), and expose snapshot capture for multimodal prompts.
- [ ] **T2.6 — 1.54" E-Paper (`SSD1681`) Sprite & Partial-Refresh Renderer** (`Amos`, `Zero`)
  - Audit `clients/eink-node` in Mirrormere (`Amos`), configure `GxEPD2` / `Seeed_GFX` on pins `D0/D1/D3/D5/D8/D10`, and implement `0.3s` partial refresh for animated companion states + full refresh every N frames to prevent ghosting.
- [ ] **T2.7 — QR Soft-AP Captive Portal Onboarding (`192.168.4.1`)** (`Zero`)
  - Render scannable Wi-Fi QR code on the 200x200 e-paper screen when unprovisioned; serve mobile captive portal to set Wi-Fi and hub URL without an on-screen keyboard.

---

## Epic 3: Backend Integration & Remote Auth (`backend/`) (Milestone M2)
- [ ] **T3.1 — Mirrormere `/api/voice/interact` Device Client Spec & SSE Parser** (`Amos`)
  - Document and implement the multipart WAV upload and SSE response parser (`transcript`, `sprite_state`, `audio_chunk`, `409`/`503` handling).
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

## Epic 5: 3D Enclosure CAD & Future Wake Models (Milestone M4)
- [ ] **T5.1 — Parametric 3D-Printed Pocket Shell (`cad/`)** (`Zero`, `Ryan`)
  - Model compact snap-fit enclosure housing the stacked XIAO + Sense + Seeed Breakout, `803040` 1000mAh LiPo bay, `1.54"` e-paper bezel, speaker grille, side tactile buttons, and slide switch cutout.
- [ ] **T5.2 — V1.1 Wake-Word & Tiny Audio-Intent Classifier Spike** (`Mike`, `Zero`, `Amos`)
  - Benchmark `microWakeWord` / `ESP-SR` and Mike's wake-word-free tiny audio-intent classifier on the ESP32-S3 vector unit (`ESP-NN`), measuring real-world mA draw against the 1000 mAh LiPo.
