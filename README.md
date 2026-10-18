# GOTCHI / SPRITE

**Pocket E-Ink AI Companion & Agent-Configurable Hardware Node**

`gotchi` (working names: **GOTCHI** / **SPRITE**) is a compact, low-power pocket hardware companion built around the **Seeed Studio XIAO ESP32S3 Sense** and a **1.54" Waveshare E-Paper** display. Heavy inference (speech-to-text, vision, LLM reasoning, and TTS) runs on backend servers, reached via home Wi-Fi or shared internet from a paired phone (BLE 5.0 relay / phone tethering / hotspot).

---

## 1. Confirmed Baseline Requirements

1. **Core Compute & Sensor Split:**
   - **On-Device (XIAO ESP32S3 Sense):** Handles button/wake inputs, microphone capture, camera framing, speaker playback, and e-paper rendering.
   - **Backend Server:** Runs Whisper ASR, vision models, agent tool execution, and TTS synthesis.
2. **Shared Phone Internet (Zero Hardware Compromise):**
   - Must run off shared internet access from a user's phone on the go without requiring a dedicated cellular/LTE modem:
     - **BLE 5.0 Phone Relay (Android / Companion Service):** Uses the ESP32-S3's native Bluetooth 5.0 (LE 2M PHY) to stay continuously bonded at low power (`~2–5mA`) and relay audio, frames, and commands through the phone's internet/Tailscale connection without running the ESP32's power-hungry Wi-Fi radio.
     - **Wi-Fi Hotspot Fallback (iOS / Universal):** Connects as a standard 2.4GHz Wi-Fi client to a phone hotspot (with iOS *Maximize Compatibility* enabled where needed).
   - Both modes use the exact same XIAO ESP32S3 Sense hardware and external u.FL antenna.
3. **100% Agent-Configurable Over USB-C & Wi-Fi (Mike's Requirement):**
   - One shared JSON command set (`get_config`, `set_config`, `set_wifi`, `self_test`, `get_logs`, `reboot`, `factory_reset`) exposed over both **USB-C serial** and **Wi-Fi HTTP**.
   - Self-describing config schema, automated hardware `self_test` (tone, mic level, camera frame, display test pattern), and dual OTA firmware slots (`ota_0` / `ota_1`) with automatic rollback.
4. **Hardware Privacy Switch:**
   - Physical mute/power switch in a 3D-printed shell.

---

## 2. Candidate Hardware BOM (~$45 Unverified Baseline)

| Component | Part / Model | Notes / Role | Est. Price |
| :--- | :--- | :--- | :--- |
| **MCU + Mic + Cam** | [Seeed Studio XIAO ESP32S3 Sense](https://thepihut.com/products/seeed-studio-xiao-esp32s3-sense) | Dual-core XTensa LX7, 8MB PSRAM, 8MB Flash, OV2640 camera, digital PDM mic, 2.4GHz Wi-Fi + BLE 5.0, LiPo charge controller | ~$17 (£13.50) |
| **Display** | [Waveshare 1.54" E-Paper Module (200x200)](https://robotshop.com/products/154-e-paper-module-200x200) | SPI 24-pin FPC e-paper (supports 4-level grayscale & fast partial refresh on SSD1681; panel variant open) | ~$12 ($11.99) |
| **Display Adapter** | [Seeed ePaper Breakout Board](https://thepihut.com/products/epaper-breakout-board) | 24-pin FPC connector + level shifting for XIAO header compatibility | ~$5 (£3.80) |
| **Audio Out** | MAX98357A I2S Class-D Amp + 1W 8Ω Micro Speaker | Voice responses and alerts | ~$6 (est.) |
| **Battery & Switch** | 400mAh–500mAh 3.7V LiPo Cell + Slide Switch | Wired to XIAO battery pads | ~$6 (est.) |
| **Enclosure** | 3D-Printed Pocket Shell | Houses stacked board, e-paper bezel, speaker, and buttons | Printed |

---

## 3. Open Design Proposals (Not Yet Locked)

- **Display Grayscale / Color Depth & Refresh Mode:** Standard SSD1681 1.54" panel (supports 4-level grayscale + `0.3s` monochrome partial refresh) vs. multi-color e-paper variants.
- **Firmware Stack:** Custom **PlatformIO (ESP-IDF / Arduino)** for live runtime JSON reconfiguration and BLE/Wi-Fi dual transport vs. **ESPHome** for rapid initial bring-up.
- **First-Boot Human Setup Flow:** Seraphyma-style QR Soft-AP captive portal (`192.168.4.1`) + two-button chord navigation (no on-screen e-ink keyboard).
- **Power Lifecycle:** BLE Light-Sleep continuous tether (`~2–5mA`) when paired to phone relay vs. Deep-Sleep + RTC/button wake when on standalone Wi-Fi hotspot.
- **Custom Carrier PCB:** Optional post-breadboard 2-layer JLCPCB carrier board combining the 24-pin FPC booster, MAX98357A amp, battery fuel gauge/divider, and tactile switches.
