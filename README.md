# GOTCHI / SPRITE

**Pocket E-Ink AI Companion & Agent-Configurable Hardware Node**

`gotchi` (working names: **GOTCHI** / **SPRITE**) is a compact, low-power pocket hardware companion (~38g assembled) built around the **Seeed Studio XIAO ESP32S3 Sense** and a **Waveshare 1.54" (200x200) SPI E-Paper** display (`SSD1681`, 4-level grayscale + `0.3s` partial refresh). It captures push-to-talk (PTT) audio and 5MP autofocus camera snapshots (`OV5640`), plays voice responses through an onboard I2S micro-speaker (`MAX98357A`) or paired phone/Discord voice channel, and delegates heavy inference (Whisper STT, vision, LLM reasoning, and Kokoro TTS) to the **Mirrormere** backend hub over home Wi-Fi, an iPhone/Android Wi-Fi hotspot, or a headless **Android BLE-to-Tailscale forwarder**.

---

## Documentation Index

- **[`docs/BOM.md`](docs/BOM.md):** Locked V1 Bill of Materials, verified part specifications, direct purchase links, and upgrade/future-proofing notes.
- **[`docs/HARDWARE_ASSEMBLY.md`](docs/HARDWARE_ASSEMBLY.md):** Step-by-step meatspace wiring guide, full GPIO pinout map (with conflict resolution for `D5`/`D7` I2S vs. ePaper `BUSY`), and V2 wake-hardware pin reservations.
- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md):** End-to-end system design covering the Mirrormere `POST /api/voice/interact` wire contract, dual-transport JSON-RPC agent configuration, Android BLE-to-Tailscale packet forwarder, and future wake-word / tiny audio-intent classifier upgrade paths.
- **[`docs/TASKS.md`](docs/TASKS.md):** V1 software, firmware, mobile relay, and enclosure engineering task board across **Zero**, **Amos**, **Ryan**, and **Mike (Arbiter)**.
- **[`AGENTS.md`](AGENTS.md):** Autonomous agent operating guide, USB-C/HTTP JSON-RPC provisioning protocol, `self_test` hardware verification contract, and security guardrails.

---

## 1. Locked V1 Architecture & Hardware Baseline

| Subsystem | V1 Locked Specification | Key Capabilities & Rationale |
| :--- | :--- | :--- |
| **Core Compute & Mic** | **Seeed Studio XIAO ESP32S3 Sense** | Dual-core XTensa LX7 (240 MHz), 8MB PSRAM, 8MB Flash, onboard PDM digital mic (`GPIO41`/`GPIO42`), Wi-Fi + BLE 5.0, integrated LiPo charger. |
| **Camera Module** | **OV5640 5MP Autofocus Camera** | Plugs into the XIAO Sense B2B camera header; voice-coil motor (VCM) single-shot autofocus (`0x3022`) for crisp document and object snapshots. |
| **Display & Adapter** | **1.54" 200x200 E-Paper (`SSD1681`) + Seeed ePaper Breakout Board** | Bare glass 24-pin FPC panel (`0.3s` partial refresh + 4-level grayscale) driven by Seeed's $5 socketed XIAO ePaper Breakout Board. |
| **Audio Output** | **MAX98357A I2S Class-D Amp + 1W 8Ω Micro-Speaker** | Driven via ESP32-S3 hardware I2S (`BCLK`, `LRCLK`, `DIN`) for spoken replies and retro Tamagotchi alert chimes; auto-mutes when routing audio to phone/Discord headphones. |
| **Controls & Power** | **800–1000 mAh LiPo (`803040`) + 2 Tactile Buttons + SPDT Slide Switch** | Hardware power disconnect switch plus Top (PTT / Deep-Sleep Wake on `RTC_GPIO`) and Bottom (Action / Back) tactile buttons. |
| **Future-Proofing** | **Reserved `RTC_GPIO` (`D2`) + I2C Bus (`D4`/`D5`) + 8MB PSRAM** | Supports V1.1 on-chip wake words (`ESP-SR` / `microWakeWord`), tiny audio-intent classifiers, or a V2 ultralow-power neural DSP daughterboard with zero rewiring. |

---

## 2. Transport & Audio Routing Modes

1. **Home Wi-Fi (Direct LAN / Tailscale):**
   - Connects directly to 2.4 GHz Wi-Fi and streams `16 kHz` mono PCM WAV (`POST /api/voice/interact`) to the Mirrormere hub, receiving SSE state events and TTS audio frames.
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
- `self_test` (automated speaker tone -> PDM mic RMS check -> `OV5640` frame checksum -> e-paper test pattern)
- `get_logs` (scrubbed of credentials/PSKs)
- `reboot` / `factory_reset` (with `ota_0` / `ota_1` automatic rollback protection)
