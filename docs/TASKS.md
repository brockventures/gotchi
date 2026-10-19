# GOTCHI / SPRITE — V1 Engineering Task Board

Tracked across **Ryan**, **Mike (Arbiter)**, **Amos**, and **Zero**. Status markers: `[ ]` Todo · `[~]` In Progress · `[x]` Done.

---

## Epic 1: Architecture, Spec & Procurement (Milestone M0)
- [x] **T1.1 — Lock V1 Hardware BOM & Pinout Allocation** (`Zero`, `Amos`, `Ryan`, `Mike`)
  - Locked 7-item single-unit shopping list in [`docs/BOM.md`](BOM.md) (`$62.32` Seeed+Waveshare+Amazon / `$70.32` Seeed+Amazon / `$80.32` All-Amazon): `XIAO ESP32S3 Sense` (with included stock camera & PDM mic; `OV5640` AF optional) + `Waveshare 1.54" E-Paper Module V2` (`SKU 12955` / `B0728BJTZC` w/ direct 8-pin PH2.0 harness, replacing discontinued Seeed breakout) + `MAX98357A` I2S amp + `1W 8Ω` cavity speaker + `803040` 1000mAh LiPo + `6x6x5mm` tactile buttons + mini SPDT slide switch.
- [x] **T1.2 — Audit Mirrormere Hub Voice Contract** (`Amos`)
  - Verified `POST /api/voice/interact` (`16 kHz` mono PCM WAV -> SSE stream) in `repos/mirrormere/api/openapi.yaml` and documented in [`docs/MIRRORMERE_VOICE_CLIENT.md`](MIRRORMERE_VOICE_CLIENT.md).
- [x] **T1.3 — Order V1 Bench Hardware Parts** (`Ryan`, `Mike`)
  - Ordered 1-unit BOM cart from [`docs/BOM.md`](BOM.md) on Amazon (Ryan, 2026-10-19).

---

## Epic 2: ESP32-S3 Core Firmware (`firmware/`) (Milestone M1)
- [x] **T2.1 — Scaffold PlatformIO Project & Dual-OTA Partition Table** (`Zero`)
  - Configure `platformio.ini` for `seeed_xiao_esp32s3` with 8MB Flash (`ota_0`, `ota_1`, `nvs`, `coredump`) and 8MB Octal PSRAM enabled.
- [x] **T2.2 — Implement Dual-Transport JSON-RPC Config & `self_test` Engine** (`Zero`, `Amos`)
  - Shared command dispatcher over USB-C CDC Serial (`115200`) and Wi-Fi HTTP (`get_config`, `set_config`, `set_wifi`, `self_test`, `get_logs`, `clear_logs`, `reboot`, `factory_reset`).
  - [x] Bounded circular log ring buffer in RAM/PSRAM (`firmware/include/log_buffer.h`, `firmware/src/log_buffer.cpp`) with unconditional credential scrubbing (`psk`, `bearer_token`) and multi-subsystem lifecycle telemetry (F6 / Issue #18).
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
- [x] **T3.1 — Mirrormere `/api/voice/interact` Device Client Spec & SSE Parser** (`Amos`, `Zero`)
  - [x] Documented wire spec in [`docs/MIRRORMERE_VOICE_CLIENT.md`](MIRRORMERE_VOICE_CLIENT.md) (PR #1): multipart WAV upload, SSE events (`state`, `transcript`, `status`, `thinking`, `reply`, `audio_chunk` at `24 kHz` default base64 PCM, `error`, `done`), and `400`/`409`/`500`/`503` handling (sprite state derived on-device from `state` events).
  - [x] Implement device multipart WAV client, SSE stream parser, and Pi Zero W POC harness (`poc/gotchi_poc.py`, `firmware/`).
  - [x] Firmware client: PR #7 (GOTCHI firmware T3.1: Mirrormere voice client (C++) + push-to-talk loop, and POC parser fix for `sentence` events).
  - [x] Multimodal single JPEG & 5-frame burst multipart upload + standalone snapshot turns (`PR #24`, Closes #17; built, unflashed).
- [x] **T3.2 — Per-Device Bearer Token Auth & Remote Tunnel Gateway** (`Amos`, `Zero`)
  - [x] Add bearer token verification middleware (`backend/gateway_auth.py`, PR #9).
  - [x] Implement reference voice gateway server (`backend/voice_gateway.py`), multimodal single & burst parser, and test suite (`tests/test_voice_gateway.py`, `PR #23`, Closes #16).
- [x] **T3.3 — Discord Voice / Headphone Audio Routing Mode** (`Zero`, `Amos`)
  - [x] Support `audio_out_mode: "speaker" | "discord_voice" | "ble_phone"` on device (NVS persistence, strict JSON-RPC validation returning `invalid_audio_out_mode`, multipart metadata inclusion, and synchronized muted on-screen `SPEAKING` sprite animation) and reference gateway routing hook (`backend/voice_gateway.py`, F8 / Issue #19; firmware built, unflashed).
  - [x] Connect reference gateway (`backend/voice_gateway.py`) `DiscordVoiceSink` (`discord_voice_bot: "zero" | "mirrormere" | "custom"`, `https://` allowlisted webhook dispatch via `run_in_executor`) and ESP32-S3 BLE peripheral fallback (`firmware/include/ble_transport.h`, `firmware/src/ble_transport.cpp`, `firmware/src/voice_client.cpp`, PR #34 / PR #36).
- [x] **T3.4 — Go Live Bidirectional Streaming Client & Gateway Relay** (`Zero`)
  - [x] Implement RFC 6455 WebSocket client (`firmware/include/live_client.h`, `firmware/src/live_client.cpp`) streaming 16 kHz PCM uplink / 24 kHz PCM downlink over `/api/live/ws` with `live_mode` off by default (F19, F21 / Issue #20; firmware built, unflashed).
  - [x] Support mid-session BTN_BOT single snapshot and 5-frame burst base64 JSON injection, BTN_TOP single-press exit, HTTP/Serial RPC polling during active sessions, and configurable `live_silence_ms` (15s default) VAD auto-timeout.
  - [x] Implement `backend/live_gateway.py` with `BearerTokenVerifier` enforcement, malformed payload handling, pluggable upstream provider adapter, and unit tests (`tests/test_live_gateway.py`).
  - [x] Implement user-customizable LLM provider configuration (`backend/llm_config.py`, `GET/PUT/POST /api/config/llm` protected by `GOTCHI_ADMIN_TOKEN`) supporting `mock` (default), metered `api_key` (`ApiKeyLiveProvider`), and gateway-preconfigured `subscription` account bridges (`SubscriptionLiveProvider`) (`tests/test_llm_config_and_sinks.py`, PR #35 / PR #36).

---

## Epic 4: Headless Android BLE-to-Tailscale Forwarder (`android-ble-forwarder/`) (Milestone M3)
- [x] **T4.1 — Define BLE GATT / L2CAP CoC Framing Protocol & ESP32-S3 BLE Peripheral** (`Zero`)
  - Specify binary packet framing for streaming PTT audio chunks, JPEG snapshots, and SSE return events over BLE 5.0 (`2M PHY`) with CRC16/CRC32 integrity checks, sequence numbering, and MTU fragmentation (`firmware/include/ble_framing.h`, `firmware/src/ble_framing.cpp`, `backend/ble_framing.py`, `tests/test_ble_framing.py`, Closes #21), plus ESP32-S3 BLE GATT UART peripheral (`firmware/include/ble_transport.h`, `firmware/src/ble_transport.cpp`) wired into `voice_client.cpp` and `main.cpp`.
- [x] **T4.2 — Build Headless Android Foreground Service** (`Zero`)
  - Lightweight Kotlin app/service (`android-ble-forwarder/`, `GotchiBleRelayService`, `BleFramingCodec`) for Ryan's Pixel that auto-bonds to GOTCHI over BLE 5.0 (`2M PHY`) in the background and forwards requests over Tailscale to the reference gateway (`POST /api/voice/interact`, Closes #22).

---

## Epic 5: Multi-Part 3D-Printed Enclosure & Future Wake Models (Milestone M4)
- [x] **T5.1 — Multi-Part Openable 3D-Printed Pocket Case (`cad/`)** (`Amos`, `Zero`, `Ryan`)
  - Model a multi-part openable enclosure in Blender / CAD sized to the locked 7-item mechanical envelope in [`docs/HARDWARE_ASSEMBLY.md`](HARDWARE_ASSEMBLY.md): Waveshare `48.0 x 33.0 mm` e-paper V2 module (`27.6 x 27.6 mm` bezel window + 4x `M2` bosses), stacked XIAO ESP32S3 Sense (`21.0 x 17.8 x 15.0 mm` w/ `USB-C` + camera/mic apertures), `803040` `40 x 30 x 8 mm` LiPo bay, `MAX98357A` + `1W 8Ω` cavity speaker grille, 2x `6x6x5mm` tactile button actuators, and recessed SPDT slide switch slot.
- [ ] **T5.2 — V1.1 Wake-Word & Tiny Audio-Intent Classifier Spike** (`Mike`, `Zero`, `Amos`)
  - Benchmark `microWakeWord` / `ESP-SR` and Mike's wake-word-free tiny audio-intent classifier on the ESP32-S3 vector unit (`ESP-NN`), measuring real-world mA draw against the 1000 mAh LiPo.

---

## Epic 6: Mirrormere & Garage Voice QA Carry-Over (PRD Section 5c — From 2:23 PM PT Onward)
- [~] **T6.1 — Go Live On-Device Acoustic Echo Cancellation (`AEC`) & Barge-In (Active Only in Go Live)** (`Zero`, `Amos`, `Mike`) — [Issue #37](https://github.com/brockventures/gotchi/issues/37)
  - [x] Implemented 64-tap NLMS adaptive Acoustic Echo Cancellation (`processLiveAecSample` in `firmware/src/audio_hal.cpp`), 300 ms full-duplex speech barge-in (`consumeLiveBargeInFlag` + `{"type":"barge_in"}` WS notification), and post-playback I2S RX DMA drain (`flushRxDmaBuffer`) **scoped strictly to active Go Live sessions** (`firmware/src/live_client.cpp`), gated behind `live_barge_in` (`false` by default in `set_config` / NVS so Go Live defaults to half-duplex + DMA drain until bench delay calibration is verified).
  - [ ] Bench verification: measure physical I2S TX-to-PDM RX DMA delay and evaluate `ESP-SR` AEC alongside the 64-tap NLMS filter on the assembled `XIAO ESP32S3 Sense` + `MAX98357A` cavity enclosure before enabling `live_barge_in` by default.
- [ ] **T6.2 — Bench Comparison of `800 ms`, `1.0 s`, and `1.5 s` Trailing Silence & Neural VAD vs. RMS** (`Zero`, `Amos`, `Mike`, `Ryan`) — [Issue #38](https://github.com/brockventures/gotchi/issues/38)
  - Keep Ryan's confirmed `1.5 s` (`1500 ms`) default `ptt_silence_ms` unchanged in firmware; on the bench, compare `800 ms`, `1.0 s`, and `1.5 s` trailing silence alongside `ESP-SR` VADNet vs. plain `50 LSB` RMS threshold, changing the default only on Ryan's explicit approval.
- [x] **T6.3 — Firmware On-Device `node_id` Regex Validation (`^[A-Za-z0-9_-]{1,64}$`)** (`Zero`) — [Issue #39](https://github.com/brockventures/gotchi/issues/39)
  - Added on-device `node_id` validation (`^[A-Za-z0-9_-]{1,64}$`, matching `backend/voice_gateway.py` in PR #36) inside `firmware/src/main.cpp` (`set_config`), returning `invalid_node_id` on malformed input.
- [ ] **T6.4 — Real Whisper STT & Per-Sentence Kokoro TTS Adapter in Reference Gateway** (`Zero`, `Amos`) — [Issue #40](https://github.com/brockventures/gotchi/issues/40)
  - Connect `backend/voice_gateway.py`'s per-sentence `tts_synthesizer` and STT hooks (added in PR #36 alongside the `1200 ms`/`5000 ms` spoken filler, `60`-word `reply_cap_words`, and `400 ms` ghost filter) to real Whisper STT and Kokoro TTS backends so standalone reference gateway deployments emit real speech audio rather than synthetic silence.
- [ ] **T6.5 — Collect Animation Timing Notes from Mike & Run Bench E-Paper Refresh QA** (`Mike`, `Amos`, `Zero`, `Ryan`) — [Issue #42](https://github.com/brockventures/gotchi/issues/42)
  - Collect animation timing and voice UX observations from Mike (`LISTENING` -> `THINKING` -> spoken filler -> `SPEAKING` -> `IDLE`) and validate `0.3 s` partial-refresh pacing and full-refresh ghosting recovery intervals on the physical Waveshare `1.54"` V2 panel once bench hardware arrives.

---

## V2 Hardware & Industrial Design Backlog
- [ ] **V2.1 — Ambient Diffused LED "Glow" Indicator When Listening** (`Ryan`, `Zero`, `Amos`) — [Issue #44](https://github.com/brockventures/gotchi/issues/44)
  - Add a diffused LED lightpipe / glow ring integrated into the lower enclosure seam that softly illuminates when Gotchi is actively listening (`LISTENING` / Go Live voice capture), inspired by current-generation Google speaker hardware.
- [ ] **V2.2 — `OV5640` 5MP Autofocus Camera Upgrade & Heatsink Clearance** (`Ryan`, `Zero`, `Amos`) — [Issue #48](https://github.com/brockventures/gotchi/issues/48)
  - Upgrade from the stock fixed-focus `OV2640`/`OV3660` Sense camera to the 5MP VCM autofocus `OV5640` module (w/ heatsink; readily available on Amazon/Seeed). Firmware (`firmware/src/camera_hal.cpp`) already auto-detects `OV5640` at boot and triggers single-shot VCM autofocus (`0x3022 = 0x08`); V2 covers ordering the module, verifying rear-shell heatsink/thermal clearance in `cad/`, and benchmarking close-up macro text/document capture and 5-frame burst latency.
- [ ] **V2.3 — Ultra-Low-Power Neural Wake Co-Processor Daughterboard (`<100 µA`)** (`Mike`, `Zero`, `Amos`)
  - Hardware escape hatch documented in [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) Section 4.4 (e.g. Syntiant `NDP120` over I2C + hardware wake interrupt) if software-only `ESP-SR` / `ESP-NN` wake-word monitoring (`T5.2`) draws too much continuous battery current for all-day untethered pocket carry.
- [ ] **V2.4 — I2C LiPo Fuel Gauge (`MAX17048`) & On-Screen Battery Telemetry** (`Zero`, `Amos`, `Ryan`)
  - Add an inline `MAX17048` I2C fuel gauge IC to report accurate state-of-charge (`%`) and low-battery warnings on the 200x200 e-paper status bar (V1 solders the `803040` LiPo directly to the XIAO charger pads without a fuel-gauge ADC).
- [ ] **V2.5 — Custom Flex/Carrier PCB & Magnetic Pogo-Pin Desk Dock** (`Ryan`, `Amos`, `Zero`)
  - Replace V1 point-to-point hand wiring (`MAX98357A`, tactile buttons, SPDT switch, Waveshare 8-pin harness) with a compact carrier PCB and magnetic pogo-pin desk charging cradle (auto-enabling `preroll_mode: "usb_host"` and continuous wake-word listening when docked).

