# GOTCHI / SPRITE

**Pocket 1-Bit E-Ink AI Companion & Agent-Configurable Hardware Node**

`gotchi` (working names: **GOTCHI** / **SPRITE**) is a compact, low-power pocket hardware companion built around the **Seeed Studio XIAO ESP32S3 Sense** and a **Waveshare 1.54" (200x200) SPI E-Paper** display. It renders 1-bit animated sprites, captures push-to-talk audio and camera snapshots, and offloads heavy inference (Whisper ASR, vision, LLM reasoning, and TTS) to backend servers over Wi-Fi or a phone hotspot.

---

## 1. Core Architecture & Compute Split

- **Edge Node (ESP32-S3 Sense):**
  - Handles wake-word / push-to-talk button chords, PDM microphone capture (Opus/PCM streaming), OV2640 camera framing, I2S audio playback, and 1-bit e-paper partial refresh (`~0.3s`).
  - Zero heavy local LLM/ASR inference on the microcontroller.
- **Server / Backend Relay:**
  - Executes speech-to-text (Whisper), vision analysis, agent orchestration, and voice synthesis, returning audio streams and sprite state transitions to the device.

---

## 2. Bill of Materials (BOM) & Hardware Baseline (~$45)

| Component | Part / Model | Notes / Role | Est. Price |
| :--- | :--- | :--- | :--- |
| **MCU + Mic + Cam** | [Seeed Studio XIAO ESP32S3 Sense](https://thepihut.com/products/seeed-studio-xiao-esp32s3-sense) | Dual-core XTensa LX7, 8MB PSRAM, 8MB Flash, OV2640 camera, digital PDM mic, 2.4GHz Wi-Fi / BLE 5.0, LiPo charge controller | ~$17 (£13.50) |
| **Display** | [Waveshare 1.54" E-Paper Module (200x200)](https://robotshop.com/products/154-e-paper-module-200x200) | SPI interface, 1-bit black/white, `0.3s` partial refresh, zero power draw when static | ~$12 ($11.99) |
| **Display Adapter** | [Seeed ePaper Breakout Board](https://thepihut.com/products/epaper-breakout-board) | 24-pin FPC connector + level shifting for XIAO pin header compatibility | ~$5 (£3.80) |
| **Audio Out** | MAX98357A I2S Class-D Amp + 1W 8Ω Micro Speaker | Drives clean voice responses and chime alerts | ~$6 |
| **Battery & Power** | 400mAh–500mAh 3.7V LiPo Cell (303040 / 503035) + Slide Switch | Hardware power/mute disconnect wired to XIAO battery pads | ~$6 |
| **Enclosure** | 3D-Printed Pocket Shell | Houses stacked board, e-paper bezel, speaker chamber, and two side tactile buttons | Printed |

---

## 3. Agent-Configurable Baseline (USB-C + Wi-Fi Parity)

Per Mike's baseline design requirement, the device is **100% configurable by an autonomous agent (Amos, Zero, etc.) over both USB-C serial and Wi-Fi HTTP**:

1. **Single Command Set, Dual Transports:**
   - Identical JSON-RPC command handler exposed over **USB-C CDC Serial (`115200` baud)** and **HTTP REST on Wi-Fi**:
     - `get_config` / `set_config`
     - `set_wifi`
     - `self_test`
     - `get_logs`
     - `reboot` / `factory_reset`
2. **Self-Describing Schema:**
   - Querying `get_config --schema` returns the live settables, types, and constraints directly from the firmware so any agent can configure the node without external documentation.
3. **Hardware Verification (`self_test`):**
   - Executes an automated loop: plays a test tone on the I2S amp, samples ambient/loopback RMS level on the PDM mic, grabs an OV2640 frame checksum, and renders a verification pattern on the 200x200 e-paper screen.
4. **Dual-Slot OTA & Rollback Recovery:**
   - Uses `ota_0` / `ota_1` partitions with signature verification and automatic boot-loop rollback. USB-C flashing remains the unbrickable hardware fallback.
5. **Security & Credential Hygiene:**
   - Per-device bearer token and Wi-Fi PSKs are stored in encrypted NVS flash and never echoed in `get_logs` or Discord outputs.

---

## 4. Human First-Boot & UX Rules (Seraphyma Adaptation)

- **Zero On-Screen Keyboards:** Typing Wi-Fi passwords on a 200x200 e-paper screen with two buttons is strictly banned.
- **QR Soft-AP Captive Portal (`192.168.4.1`):**
  - If unprovisioned over USB-C, first boot launches an open/PIN soft-AP (`GOTCHI-XXXX`) and draws a scannable QR code on the e-paper screen.
  - Works out of the box on iOS and Android without a companion app.
- **iOS Hotspot Compatibility:**
  - Because the ESP32-S3 radio is 2.4GHz-only, iPhone users (iPhone 12+) enable **Maximize Compatibility** under Personal Hotspot settings when tethering on the go.
- **Two-Button 4-Action Chord:**
  - **Top Tap:** Next / Cycle
  - **Top Hold:** Select / Confirm (or Push-to-Talk on Home screen)
  - **Bottom Tap:** Down / Secondary cycle
  - **Bottom Hold:** Back / Cancel

---

## 5. Open Engineering Questions

1. **Firmware Foundation:** Start with **ESPHome** (fast bring-up, built-in safe mode & OTA, though config changes recompile) vs. **ESP-IDF / PlatformIO** (true runtime JSON reconfiguration, native Opus streaming, custom partial-refresh sprite engine).
2. **XIAO ESP32S3 Sense Pin Multiplexing:** Verify exact GPIO allocation across the B2B camera/mic expansion board (`D0–D10` vs. internal camera/SD/mic pins), the Seeed ePaper breakout (SPI `SCK`, `MOSI`, `CS`, `DC`, `RST`, `BUSY`), and the MAX98357A I2S amp (`BCLK`, `LRCLK`, `DIN`) plus 2 buttons.
3. **Backend Reachability from Mobile Hotspot:** Evaluate lightweight outbound WebSocket/HTTPS tunnel vs. Tailscale/WireGuard micro-client for reaching the Crab Cavern voice relay from behind carrier NAT.
