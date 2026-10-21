# GOTCHI Headless Android Smart-Pipe BLE Companion Relay (`android-ble-forwarder/`)

Headless Android foreground companion service (`F18` / `T4.2`) for out-of-home pocket operation. Eliminates mobile Wi-Fi hotspot battery drain by bonding to GOTCHI over **BLE 5.0 (`2M PHY`)** and relaying voice/vision turns over standard **HTTPS (`443`, Cloudflare Tunnel / reverse proxy — zero Tailscale or VPN required on the phone)** or LAN (`:8765`) to the GOTCHI Voice Gateway (`POST /api/voice/interact`).

---

## Architecture & Smart Pipe Offload

1. **Auto-Scan & BLE 5.0 2M PHY Bonding:**
   - `GotchiBleRelayService` runs as a persistent `connectedDevice` foreground service (`START_STICKY`) started automatically on boot via `BootCompletedReceiver`.
   - Filters on GOTCHI's BLE GATT UART Service UUID (`6E400001-B5A3-F393-E0A9-E50E24DCCA9E`), negotiates `2M PHY` and a `512-byte` ATT MTU (`492-byte` max payload per packet after the 16-byte header and 4-byte CRC32 trailer).

2. **4-Bit IMA ADPCM BLE Audio Transcoding (`ImaAdpcmCodec` in `BleFramingCodec.kt`):**
   - **Uplink (`64 kbps` vs `256 kbps` raw PCM — 4x faster):** Reassembles `AUDIO_CHUNK` frames tagged with `FLAG_ADPCM` (`0x08`) / `GAD1` container magic (`16 kHz` 4-bit IMA ADPCM) and transcodes them on the phone into a standard 44-byte RIFF/WAVE `16 kHz` 16-bit mono PCM payload before posting to `/api/voice/interact`.
   - **Downlink (`96 kbps` vs `384 kbps` raw PCM — 4x faster):** When `audio_out_mode == "speaker"` over BLE, transcodes incoming `sentence` / `audio_chunk` `24 kHz` 16-bit PCM SSE payloads into `GAD1` 4-bit IMA ADPCM (`"format": "adpcm"`) before writing fragmented `SSE_EVENT` (`0x04`) frames to `CHAR_RX` (`6E400002-...`), where ESP32-S3 `gotchi_audio::playBase64AdpcmChunk` decodes and plays them in real time.
   - **Phone / Earbud Audio Routing (`audio_out_mode == "ble_phone"`):** Intercepts `sentence` / `audio_chunk` SSE events and plays the 24 kHz 16-bit mono PCM directly through Android `AudioTrack` (`USAGE_ASSISTANT`) to the phone speaker or paired Bluetooth earbuds while still forwarding `state` (`SPEAKING`) and `done` events to GOTCHI so the e-paper sprite animates in sync.

3. **Dead-Zone Store-and-Forward Spooling (`offline_spool/`):**
   - When the phone is in a cellular/Wi-Fi dead zone or the gateway returns `502`/`503`/`504`, `GotchiBleRelayService` spools the turn (`wav_b64`, `images`, `commit_meta`, `location_meta`) into `filesDir/offline_spool` (bounded to 64 items FIFO) and immediately returns an `offline_queued` SSE status + `done` frame over BLE.
   - `ConnectivityManager.NetworkCallback` automatically drains and replays spooled turns to `/api/voice/interact` as soon as HTTPS/LAN connectivity returns.

4. **Optional Coarse GPS Metadata Tagging:**
   - When `ACCESS_COARSE_LOCATION` is granted, `readCoarseLocationMeta()` attaches cached passive/network location coordinates (`lat`, `lon`, `location_accuracy_m`) from `LocationManager.getLastKnownLocation` to `/api/voice/interact` turns with zero active GPS radio drain.

---

## Runtime Configuration via ADB Intent

Configure the target gateway URL (standard HTTPS domain or LAN IP), per-device bearer token, and audio routing mode without rebuilding:

```bash
adb shell am start-foreground-service \
  -n ventures.brock.gotchi.forwarder/.GotchiBleRelayService \
  --es gateway_url "https://gotchi.example.com" \
  --es bearer_token "<YOUR_DEVICE_TOKEN>" \
  --es node_id "gotchi-pocket-01" \
  --es audio_out_mode "ble_phone"
```
