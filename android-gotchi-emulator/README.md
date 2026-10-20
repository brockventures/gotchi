# GOTCHI Pocket Android Emulator (`android-gotchi-emulator/`)

Standalone Android hardware emulator app (`ventures.brock.gotchi.emulator`), forked from `android-ble-forwarder/` so the headless BLE relay service remains completely untouched and both apps can be installed side-by-side on any Android phone.

---

## Key Capabilities & Hardware Parity

1. **Exact 200x200 1-Bit Monochrome E-Paper Viewport (`GotchiEpaperView.kt`):**
   - Renders the exact 200x200 pixel layout from `poc/gotchi_poc.py` and `firmware/src/epd_panel.cpp` across all 9 states (`idle`, `listening`, `transcribing`, `thinking`, `synthesizing`, `speaking`, `error`, `busy`, `offline`).
   - Includes both the default **Gotchi** vector companion face and the bundled 1-bit **Zero** sprite skin (`app/src/main/assets/zero_skin/zero_<state>_200x200_1bit.png`).
   - Emulates the `RefreshTracker` partial/full refresh cadence (`maxConsecutivePartials = 8`, `fullRefreshMinutes = 15.0`) with realistic `300 ms` partial transitions and the `2.0 s` black/white inversion flash on full refreshes.

2. **Tactile & Physical Button Emulation (`GotchiEmulatorActivity.kt`):**
   - **`BTN_TOP` (On-Screen Button + Physical `Volume Up`):**
     - **Hold / Release:** Captures `16 kHz` 16-bit mono PCM audio from the phone microphone (`AudioRecord`) with a `500 ms` circular pre-roll buffer, wraps it in a 44-byte RIFF WAV header, and streams the turn to `POST /api/voice/interact`.
     - **Double-Press:** Launches a full-duplex **Go Live** WebSocket session (`/api/live/ws`) with Android hardware `AcousticEchoCanceler` and `300 ms` speech barge-in (`{"type":"barge_in"}`).
   - **`BTN_BOT` (On-Screen Button + Physical `Volume Down`):**
     - **Single Press:** Captures a single JPEG snapshot (`image`) and attaches it to the next voice turn.
     - **Hold (`>= 500 ms`):** Captures a 5-frame JPEG burst (`image_0`..`image_4`) and dispatches a standalone multimodal vision turn.
   - **Bench VAD Selector (`T6.2`):** One-tap toggle between `800 ms`, `1000 ms`, and `1500 ms` trailing silence thresholds.

3. **Zero-Diff Live Backend Integration (`GotchiEmulatorEngine.kt`):**
   - Connects directly to `backend/voice_gateway.py` (`POST /api/voice/interact`) and `backend/live_gateway.py` (`/api/live/ws`) over LAN (`:8765`) or Cloudflare Tunnel (`https://` on port `443`) using per-device `Authorization: Bearer <token>`.
   - Parses both `sentence` (`audio_b64` from PR #71's lookahead TTS pipeline) and legacy `audio_chunk` SSE events, walking RIFF/WAV headers (`extractPcmFromWavOrRaw`) and playing `24 kHz` 16-bit mono PCM through Android `AudioTrack` (`USAGE_ASSISTANT`).

---

## Runtime Configuration via ADB Intent

```bash
adb shell am start   -n ventures.brock.gotchi.emulator/.GotchiEmulatorActivity   --es gateway_url "https://gotchi.example.com"   --es bearer_token "<YOUR_DEVICE_TOKEN>"   --es node_id "gotchi-android-emu-01"   --es skin "zero"   --el ptt_silence_ms 1000
```
