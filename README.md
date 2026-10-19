# GOTCHI / SPRITE

**Pocket E-Ink AI Companion & Agent-Configurable Hardware Node**

`gotchi` (working names: **GOTCHI** / **SPRITE**) is a compact, low-power pocket hardware companion (~38g assembled) built around the **Seeed Studio XIAO ESP32S3 Sense** and the **Waveshare 1.54" (200x200) E-Paper Module V2** (`SKU 12955` / Amazon `B0728BJTZC`, `SSD1681`, 2 gray levels B/W, `0.3s` partial / `2.0s` full refresh). It captures push-to-talk (PTT) audio and camera snapshots (using the included stock `OV2640`/`OV3660` camera or optional `OV5640` 5MP autofocus upgrade), plays voice responses through an onboard I2S micro-speaker (`MAX98357A`) or paired phone/Discord voice channel, and delegates heavy inference (Whisper STT, vision, LLM reasoning, and Kokoro TTS) to the **Mirrormere** backend hub over home Wi-Fi, an iPhone/Android Wi-Fi hotspot, or a headless **Android BLE-to-Tailscale forwarder**.

---

## Documentation Index

- **[`docs/BOM.md`](docs/BOM.md):** Locked V1 8-item Bill of Materials, verified 1-unit shopping list (`$68.81` / `$76.81` / `$86.81`), bench wire/insulation consumables, and optional V2 camera upgrade.
- **[`docs/HARDWARE_ASSEMBLY.md`](docs/HARDWARE_ASSEMBLY.md):** Step-by-step meatspace wiring guide, direct 8-pin PH2.0 display harness map, GPIO pinout allocation (`D0–D10`), 4x `220 kΩ` battery/wall-sense dividers, and mechanical component dimensions for the multi-part 3D-printed enclosure.
- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md):** End-to-end system design covering the Mirrormere `POST /api/voice/interact` wire contract, dual-transport JSON-RPC agent configuration, Android BLE-to-Tailscale packet forwarder, and future wake-word / tiny audio-intent classifier upgrade paths.
- **[`docs/MIRRORMERE_VOICE_CLIENT.md`](docs/MIRRORMERE_VOICE_CLIENT.md):** Verified Mirrormere `POST /api/voice/interact` SSE event specification and `client/eink-node/` refresh policy notes.
- **[`docs/TASKS.md`](docs/TASKS.md):** V1 software, firmware, mobile relay, and multi-part Blender/CAD enclosure task board across **Zero**, **Amos**, **Ryan**, and **Mike (Arbiter)**.
- **[`AGENTS.md`](AGENTS.md):** Autonomous agent operating guide, USB-C/HTTP JSON-RPC provisioning protocol, `self_test` hardware verification contract, and security guardrails.

---

## 1. Locked V1 Architecture & Hardware Baseline (8-Item BOM)

| Subsystem | V1 Locked Specification | Key Capabilities & Rationale |
| :--- | :--- | :--- |
| **Core Compute & Mic** | **Seeed Studio XIAO ESP32S3 Sense** (`$13.99` Seeed / `$23.99` Amazon `B0C69FFVHH`) | Dual-core XTensa LX7 (240 MHz), 8MB PSRAM, 8MB Flash, onboard PDM digital mic (`GPIO41`/`GPIO42`), Wi-Fi + BLE 5.0, integrated LiPo charger. |
| **Camera Module** | **Stock Sense Camera (`OV2640`/`OV3660`, Included)** · *Optional V2.2:* **Seeed `OV5640` 5MP AF (`$11.99`)** | Stock camera plugs into the XIAO Sense B2B header at `$0` extra cost; firmware auto-detects the sensor and enables VCM autofocus (`0x3022`) if upgraded to `OV5640`. |
| **Display Module** | **Waveshare 1.54" E-Paper Module V2** (`$9.99` Waveshare `SKU 12955` / `$17.99` Amazon `B0728BJTZC`) | Complete `48.0 x 33.0 mm` module (`200x200` `SSD1681`, 2 gray levels B/W, `0.3s` partial / `2.0s` full refresh, onboard 3.3V/5V translator, 4x M2 holes) with included 8-pin PH2.0 wire harness. Eliminates the discontinued Seeed ePaper Breakout. |
| **Audio Output** | **MAX98357A I2S 3W Amp (`B0DPJRLMDJ`) + 1W 8Ω Cavity Speaker (`B0D7S8FFKY`)** | Driven via ESP32-S3 hardware I2S (`BCLK` on silent `D7`, `LRCLK` on `D6`, `DIN` on `D9`) for spoken replies and Tamagotchi chimes; auto-mutes when routing audio to phone/Discord headphones. |
| **Controls, Power & Fuel Gauge** | **1000 mAh `803040` LiPo (`B0FRFY7KLH`) + 2x `6x6x5mm` Tactile Buttons (`B07VSNN9S2`) + Mini SPDT Slide Switch (`B0FNK8B1YV`) + 4x `220 kΩ` Resistors (`B0F4P352BB`)** | Hardware battery cutoff slide switch, Top (`BTN_TOP` PTT / Wake + `5V VBUS` wall-brick sense on `D2` / `ADC1_CH2`), and Bottom (`BTN_BOT` Camera Snap/Burst + `VBAT` `0–100%` LiPo fuel gauge on `D4` / `ADC1_CH4`). |
| **1-Unit Cart Totals** | **`$68.81`** (Seeed + Waveshare + Amazon) · **`$76.81`** (Seeed + Amazon) · **`$86.81`** (All-Amazon) | Verified single-unit prototype totals before shipping and tax; see [`docs/BOM.md`](docs/BOM.md) for itemized links and bench consumables. |

---

## 2. Transport & Audio Routing Modes

1. **Home Wi-Fi (Direct LAN / Tailscale):**
   - Connects directly to 2.4 GHz Wi-Fi and streams `16 kHz` mono PCM WAV (`POST /api/voice/interact`) to the Mirrormere hub, receiving SSE state events and `24 kHz` PCM TTS audio chunks.
2. **Android Walk-Out-The-Door Roaming (Headless BLE-to-Tailscale Forwarder):**
   - Bonds over **BLE 5.0 (`L2CAP CoC` / GATT)** (`~2–5 mA` idle draw) to a lightweight headless Android background service on Ryan's Pixel, forwarding audio/snapshots over Tailscale without toggling the phone's Wi-Fi hotspot.
3. **iOS / Universal On-The-Go Mode (2.4 GHz Hotspot + Discord Backdoor):**
   - Connects to an iPhone Personal Hotspot (`Maximize Compatibility` enabled for 2.4 GHz).
   - Plays replies out loud via the onboard `MAX98357A` speaker by default, or routes voice responses into AirPods via a private 1-on-1 Discord voice channel (or lock-screen PWA audio stream) with zero iOS app maintenance.

---

## 3. Agent-Configurable Baseline (USB-C + HTTP Parity)

Every GOTCHI / SPRITE node exposes an identical JSON command contract over **USB-C CDC Serial (`115200` baud)** and **Wi-Fi HTTP**:
- `get_config` (supports `"schema": true` for self-describing agent discovery)
- `set_config` / `set_wifi`
- `self_test` (automated speaker tone -> PDM mic RMS check -> camera frame checksum -> e-paper test pattern)
- `get_logs` (scrubbed of credentials/PSKs)
- `reboot` / `factory_reset` (with `ota_0` / `ota_1` automatic rollback protection)
