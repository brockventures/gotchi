# GOTCHI Headless Android BLE-to-Tailscale Relay (`android-ble-forwarder/`)

Headless Android foreground companion service (`F18` / `T4.2`) for out-of-home pocket operation. Eliminates mobile Wi-Fi hotspot battery drain by bonding to GOTCHI over **BLE 5.0 (`2M PHY`)** and relaying voice/vision turns over the phone's existing **Tailscale** tunnel to the GOTCHI Voice Gateway (`POST /api/voice/interact`).

---

## Architecture & Data Flow

1. **Auto-Scan & BLE 5.0 2M PHY Bonding:**
   - `GotchiBleRelayService` runs as a persistent `connectedDevice` foreground service (`START_STICKY`) started automatically on boot via `BootCompletedReceiver`.
   - Filters on GOTCHI's BLE GATT UART Service UUID (`6E400001-B5A3-F393-E0A9-E50E24DCCA9E`), negotiates `2M PHY` and a `512-byte` ATT MTU (`492-byte` max payload per packet after the 16-byte header and 4-byte CRC32 trailer).

2. **Binary Uplink Reassembly (`BleFramingCodec.kt`):**
   - Decodes incoming `CHAR_TX` (`6E400003-...`) packets using the locked `T4.1` 16-byte header (`magic = 0x4742`, `frame_type`, `flags`, `frame_index`, `reserved`, `seq_num`, `chunk_idx`, `total_chunks`, `payload_len`, `header_crc16` CCITT-FALSE) and 4-byte IEEE 802.3 `crc32` trailer.
   - Reassembles `AUDIO_CHUNK` (`16 kHz` 16-bit mono PCM WAV), `IMAGE_FRAME` (`0..4` single or 5-frame JPEG burst), and triggers the upstream HTTP request on `TURN_COMMIT`.

3. **Tailscale Multipart Relay & Downlink SSE Streaming:**
   - Sends `POST /api/voice/interact` (`node_id`, `audio_out_mode`, `audio`, `image` or `image_0`..`image_4`) with `Authorization: Bearer <token>` over Tailscale.
   - Streams SSE events (`state`, `transcript`, `reply`, `audio_chunk`, `done`, `error`) back down `CHAR_RX` (`6E400002-...`) as fragmented `SSE_EVENT` (`0x04`) BLE frames.
   - **Phone / Earbud Audio Routing (`audio_out_mode == "ble_phone"`):** Intercepts `audio_chunk` SSE events and plays the 24 kHz 16-bit mono PCM directly through Android `AudioTrack` (`USAGE_ASSISTANT`) to the phone speaker or paired Bluetooth earbuds while still forwarding `state` (`SPEAKING`) and `done` events to GOTCHI so the e-paper sprite animates in sync.

---

## Runtime Configuration via ADB Intent

Configure the target gateway URL, per-device bearer token, and audio routing mode without rebuilding:

```bash
adb shell am start-foreground-service \
  -n ventures.brock.gotchi.forwarder/.GotchiBleRelayService \
  --es gateway_url "http://100.64.0.1:8080" \
  --es bearer_token "<YOUR_DEVICE_TOKEN>" \
  --es node_id "gotchi-pocket-01" \
  --es audio_out_mode "ble_phone"
```
