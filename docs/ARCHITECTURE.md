# GOTCHI / SPRITE — System Architecture & Wire Contracts

---

## 1. End-to-End Topology

```
+-------------------------------------------------------------------+
|                     GOTCHI / SPRITE EDGE NODE                     |
|                (Seeed Studio XIAO ESP32S3 Sense)                  |
|                                                                   |
|  [BTN_TOP: PTT/Wake] ---> [PDM Mic 16kHz PCM]                     |
|  [BTN_BOT: Snap/Nav] ---> [Stock Cam / Optional OV5640 AF]        |
|  [1.54" E-Paper]     <--- [GxEPD2 / Seeed GFX]                    |
|  [MAX98357A Speaker] <--- [I2S Audio Pipeline]                    |
+---------+--------------------------+-----------------------+------+
          | (A) Home Wi-Fi /         | (B) Walk-Out-The-Door | (C) USB-C Serial
          |     iPhone Hotspot       |     BLE 5.0 L2CAP/GATT|     115200 baud
          v                          v                       v
  (Direct HTTP/SSE)        +-------------------+     +---------------+
          |                | Pixel 8 Pro       |     | Local Agent   |
          |                | Headless Android  |     | Provisioning  |
          |                | BLE Forwarder     |     | (Amos / Zero) |
          |                +---------+---------+     +---------------+
          |                          | (Tailscale)
          +------------+-------------+
                       |
                       v
+-------------------------------------------------------------------+
|                   MIRRORMERE / DISCORD BACKEND HUB                |
|                                                                   |
|  • POST /api/voice/interact (multipart/form-data -> SSE stream)   |
|  • Whisper STT -> Agent Brain -> Kokoro TTS                       |
|  • Optional Discord Voice Channel Audio Output (AirPods Backdoor) |
+-------------------------------------------------------------------+
```

---

## 2. Mirrormere Backend Wire Contract (`POST /api/voice/interact`)

As verified by **Amos** against `repos/mirrormere/api/openapi.yaml`, the Mirrormere hub already exposes the exact voice interaction endpoint GOTCHI needs with zero backend changes required for V1 local operation:

### Request (`multipart/form-data`)
```http
POST /api/voice/interact HTTP/1.1
Host: <mirrormere-hub>:8080
Authorization: Bearer <device-token>
Content-Type: multipart/form-data; boundary=---GotchiBoundary

---GotchiBoundary
Content-Disposition: form-data; name="audio"; filename="ptt.wav"
Content-Type: audio/wav

<16 kHz, 16-bit mono PCM WAV payload>
---GotchiBoundary
Content-Disposition: form-data; name="node_id"

gotchi-ryan-01
---GotchiBoundary
Content-Disposition: form-data; name="session_id"

sess-20261018-01
---GotchiBoundary--
```

### Response (`text/event-stream` Server-Sent Events)
- Streams structured SSE events back to the edge node as the pipeline progresses:
  - `event: state` -> `{"state": "received" | "transcribing" | "thinking" | "synthesizing"}` transitions the 200x200 e-paper companion sprite using `0.3s` partial refresh (`2.0s` full refresh every N frames)
  - `event: transcript` / `event: reply` -> updates e-paper status/subtitle if enabled
  - `event: audio_chunk` -> streams base64 PCM chunks (`24 kHz` default) to the `MAX98357A` I2S ring buffer in 8MB PSRAM (unless `audio_out_mode == "discord_voice"` is active for headphone listening)
  - `event: error` / `event: done` -> returns companion sprite to error/idle state (see [`docs/MIRRORMERE_VOICE_CLIENT.md`](MIRRORMERE_VOICE_CLIENT.md) for full SSE schema)
- **Status Codes:**
  - `200 OK`: SSE stream active
  - `409 Conflict`: Another interaction is already in flight
  - `503 Service Unavailable`: Hub voice pipeline disabled

---

## 3. Headless Android BLE-to-Tailscale Forwarder (V1 Roaming)

To give Ryan zero-touch connectivity when walking out of home Wi-Fi range without toggling his phone's Wi-Fi hotspot or burning ESP32 Wi-Fi idle power (`60–95 mA` vs. `2–5 mA` on BLE):

1. **Transport Selection State Machine (On-Device):**
   - **Priority 1 (Home Wi-Fi):** If known home SSID is in range, connect directly over Wi-Fi.
   - **Priority 2 (BLE Companion Link):** When bonded to the Pixel's GATT/L2CAP service (`UUID: 6E400001-B5A3-F393-E0A9-E50E24DCCA9E`), keep the ESP32 Wi-Fi radio powered off (`esp_wifi_stop()`) and tunnel PTT audio + camera frames over BLE 5.0 (`2M PHY`, `L2CAP CoC` or 512-byte MTU GATT notifications).
   - **Priority 3 (Phone Hotspot Fallback — iOS / Universal):** If BLE relay is unavailable, wake Wi-Fi and connect to the configured mobile hotspot (`Maximize Compatibility` 2.4 GHz on iPhone).
2. **Android Foreground Service (`android-ble-forwarder/`):**
   - Minimal headless Kotlin service (~250 lines) running an persistent BLE Central manager.
   - Reassembles incoming audio/snapshot frames from GOTCHI, attaches the device's bearer token, and dispatches `POST /api/voice/interact` over the phone's active **Tailscale** interface to the Mirrormere hub.
   - Streams the hub's SSE response events back down the BLE channel to GOTCHI (and optionally plays TTS audio directly to Bluetooth earbuds paired to the phone).

---

## 4. Adaptable Wake Architecture (V1 PTT -> V1.1 Classifier / Wake-Word)

Per **Ryan** and **Mike's** design lock, V1 ships with **Push-to-Talk (`BTN_TOP`)** as the primary interaction model while keeping the hardware and firmware 100% ready for hands-free operation:

1. **Phase 1 (V1 Default): Hardware Push-to-Talk (`BTN_TOP` on `D2` / `RTC_GPIO3`)**
   - Between interactions, the ESP32-S3 enters light sleep (or deep sleep with `ext0` wake on `GPIO3` low).
   - Pressing `BTN_TOP` immediately starts streaming 16 kHz PDM audio from `GPIO41`/`42` into a circular pre-roll ring buffer in the 8MB PSRAM until release.
2. **Phase 2 (V1.1 Firmware Toggle): On-Chip Wake-Word (`ESP-SR` / `microWakeWord`)**
   - Uses the exact same onboard PDM microphone and 8MB PSRAM.
   - Enabled via `set_config {"wake_mode": "wake_word"}` (automatically enabled when on USB-C desk power, or selectable on battery using the 1000 mAh LiPo headroom).
3. **Phase 3 (V2 Experiment — Mike's Vision): Wake-Word-Free Tiny Audio Classifier**
   - Runs continuous local Voice Activity Detection (VAD) + a lightweight int8 audio-intent / speech-directedness model on the ESP32-S3's vector extensions (`ESP-NN`), forwarding speech segments without requiring a rigid *"Hey Gotchi"* prefix.
4. **Hardware Escape Hatch (`D4` / `RTC_GPIO5` Reserved):**
   - If a future hardware revision adds a dedicated `<100 µA` neural DSP daughterboard (e.g. Syntiant `NDP120`), it wires straight into the reserved `D4` (`RTC_GPIO5`) wake pin and `I2C` bus without modifying the V1 wiring harness.

---

## 5. Dual-Transport Agent Configuration Protocol (`USB-C` + `HTTP`)

Both **USB-C Serial (`115200` baud, newline-delimited JSON)** and **HTTP (`POST /api/rpc`)** invoke the same C++ command dispatcher:

| Command | Payload Parameters | Behavior |
| :--- | :--- | :--- |
| `get_config` | `{"schema": true}` (optional) | Returns active NVS configuration values (secrets masked) plus JSON schema of all configurable keys, types, and enums. |
| `set_config` | `{"key": "val", ...}` | Validates against schema, persists to NVS, and applies live without recompiling (`hub_url`, `voice_url`, `node_id`, `wake_mode`, `audio_out_mode`, `display_mode`). |
| `set_wifi` | `{"ssid": "...", "psk": "...", "slot": 0}` | Stores primary (Home) or secondary (Hotspot) Wi-Fi credentials in encrypted NVS. |
| `self_test` | `{}` | Runs full hardware loop: speaker tone -> PDM mic RMS -> camera sensor ID + JPEG frame CRC -> e-paper pattern, returning structured JSON pass/fail receipts. |
| `get_logs` | `{"lines": 50}` | Returns recent ring-buffer diagnostic logs (scrubbed of tokens/PSKs). |
| `reboot` | `{"mode": "normal" \| " bootloader"}` | Cleanly restarts the MCU or enters ROM USB bootloader. |
| `factory_reset` | `{"confirm": true}` | Wipes user NVS namespace and reboots into QR Soft-AP onboarding mode (`192.168.4.1`). |
