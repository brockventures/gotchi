# GOTCHI / SPRITE: Product Requirements (V1)

Status: V1 baseline synced against `main` (`PR #1`–`PR #50`). Every requirement names its source. A line marked **OPEN** is a decision nobody has made; nothing in this file was invented to fill a gap.

## 1. Goal

A pocket e-ink companion. The user holds a button and speaks. The device sends the speech to a voice backend over the Mirrormere wire protocol and plays the spoken reply, showing a character face that reflects what it is doing.

GOTCHI uses no Mirrormere hardware. The Pi Zero panel and the Pi gateway on the bench may be used to test software, and for nothing else; the locked V1 bill of materials is the hardware goal, changed only by what testing shows (Mike, #gotchi 2026-10-19 09:27 and 09:29). Which backend a unit talks to is set per unit with `voice_url`.

Sources: `README.md`; Mike and Ryan in #gotchi, 2026-10-18.

## 2. Users and contexts

- Mike and Ryan, one unit each for V1 (`docs/BOM.md`).
- Desk use first. Wearable form factor comes after the tech works (Mike, #gotchi 2026-10-18 22:08).
- Connectivity: home Wi-Fi and phone hotspot. Android BLE relay stays in scope (Ryan); iOS is not prioritised (Mike).

## 3. Core flow: one push-to-talk turn

1. User holds (or taps in hybrid/tap mode) the top button. Device records and shows LISTENING.
2. User releases (or pauses for `vad_silence_ms`). Device uploads the recording and shows TRANSCRIBING.
3. Hub streams events. Device shows THINKING or SYNTHESIZING, then plays audio as it arrives and shows SPEAKING.
4. Stream ends. Device returns to IDLE.

Source: `docs/MIRRORMERE_VOICE_CLIENT.md`, `firmware/src/main.cpp`.

## 4. Functional requirements

| ID | Requirement | Source | Status |
|---|---|---|---|
| F1 | Push-to-talk is the primary input (`hybrid`, `tap`, or `hold` via `input_mode`) | Mike and Ryan, #gotchi | Built, unflashed (`firmware/src/main.cpp`) |
| F2 | 500 ms pre-roll so the start of speech is not lost | `docs/TASKS.md` T2.3 | Built, unflashed (`firmware/src/audio_hal.cpp`) |
| F3 | Reply audio plays as it streams, with no limit on reply length | Ryan, #gotchi 2026-10-19 08:56 | Built: gateway streams about 11 KB chunks, measured live 2026-10-19 |
| F4 | Nine on-screen states: idle, listening, transcribing, thinking, synthesizing, speaking, error, busy, offline | `firmware/include/ui_state.h` | Built, verified on a bench panel |
| F5 | Two skins, `zero` (default) and `gotchi`, set with `set_config` | Zero, PR #9 | Built, unflashed |
| F6 | Configuration and scrubbed ring-buffer logs (`get_config`, `set_config`, `get_logs`, `clear_logs`) over USB serial and Wi-Fi JSON-RPC | `README.md` section 3, PR #26 | Built, unflashed (`firmware/src/log_buffer.cpp`, `firmware/src/main.cpp`) |
| F7 | Optional bearer token on Wi-Fi RPC and on hub requests | `docs/TASKS.md` T3.2 | Built on device and reference gateway (`backend/gateway_auth.py`, `backend/voice_gateway.py`, `backend/live_gateway.py`, PR #9 / PR #23 / PR #35) |
| F8 | Reply audio routing: `speaker`, `discord_voice`, `ble_phone` | `docs/TASKS.md` T3.3 | Built on device and reference gateway (`DiscordVoiceSink`, `ble_transport.cpp`, PR #27 / PR #34 / PR #36) |
| F9 | Camera snapshot on the bottom button | `README.md` | Built on device and reference gateway (`firmware/src/main.cpp`, `backend/voice_gateway.py`, PR #12 / PR #23 / PR #24) |
| F10 | First-boot Wi-Fi setup by QR code and captive portal | `docs/TASKS.md` T2.7 | Built, unflashed (`firmware/src/onboarding_portal.cpp`) |
| F11 | Recording cap raised to 120 s in 8 MB PSRAM (`3.84 MB` WAV buffer) | Ryan, #gotchi 2026-10-19 09:09 & 09:15 | Built, unflashed (`cfg.ptt_max_ms = 120000`, PR #25) |
| F12 | Pre-roll runs on external USB/wall power by default (`preroll_mode: "usb_host"`), with `"always"` and `"off"` settings | Ryan, #gotchi 2026-10-19 09:09 | Built, unflashed (`applyPrerollPolicy` in `firmware/src/main.cpp`, PR #25 / PR #50) |
| F13 | Top button is for speaking only. While a reply plays, pressing it cancels or mutes the reply and returns to idle. It does not start a new recording | Ryan, #gotchi 2026-10-19 09:45 | Built, unflashed (PR #12 / PR #24) |
| F14 | Bottom button is for the camera only. A short press takes a snapshot that attaches to the next voice prompt if that prompt starts within the attach window; otherwise it is sent alone for the bot to comment on. A short press during a recording takes a snapshot and attaches it to the turn in progress | Ryan, #gotchi 2026-10-19 09:15, 09:45, 09:47 | Built, unflashed (PR #12 / PR #24) |
| F15 | Each unit points `voice_url` at its own backend; Ryan's unit goes straight to Zero's gateway | Ryan, #gotchi 2026-10-19 09:09 | Built (`voice_url` in `GotchiConfig`) |
| F16 | Battery life with normal usage: 48 hours without wake word, 24 hours with wake word enabled | Ryan, #gotchi 2026-10-19 09:18 | Not measured. Normal usage: 20 push-to-talk turns a day (Ryan, #gotchi 2026-10-19 09:21) |
| F17 | Hotspot test: from a cold start on a phone hotspot, one push-to-talk turn completes and the reply plays | Proposed by Amos, accepted by Ryan, #gotchi 2026-10-19 09:21 | Not tested on physical unit |
| F18 | BLE relay test: the same turn with the phone away from home Wi-Fi | Proposed by Amos, accepted by Ryan, #gotchi 2026-10-19 09:21 | Built (`android-ble-forwarder/`, `ble_transport.cpp`, PR #28 / PR #29 / PR #34); not tested on physical unit |
| F19 | "Go Live" mode: a continuous two-way voice session through a live multimodal model, entered on purpose and ending on a timeout. Configurable (`live_mode`, default `false`) | Ryan, #gotchi 2026-10-19 09:21 and 09:35 | Built (`firmware/src/live_client.cpp`, `backend/live_gateway.py`, `backend/llm_config.py`, PR #31 / PR #35 / PR #36); unflashed |
| F20 | Long press on the bottom button (`>= 700 ms`) takes a burst of five photos over 3 seconds and sends them together | Ryan, #gotchi 2026-10-19 09:45 | Built on device and reference gateway (`captureBurstFrames`, `backend/voice_gateway.py`, `backend/live_gateway.py`, PR #23 / PR #24 / PR #31); Mirrormere room gateway image handler still needed (see section 6) |
| F21 | Saying "Go Live" as a whole-utterance voice command starts a Live session (when `live_mode` is enabled) | Ryan, #gotchi 2026-10-19 09:45 | Built, unflashed (`isWholeUtteranceGoLive` in `firmware/src/main.cpp`, PR #24 / PR #31) |
| F22 | Battery percentage in the screen header (`85%`, `85%+` while on external power), read from a `220 kΩ / 220 kΩ` divider on `D4` (`GPIO5` / `ADC1_CH4`) | Ryan, #gotchi 2026-10-19 16:04 and 16:14 ("promote both to v1 prd") | Built in firmware, merged (PR #50); not measured on hardware |
| F23 | Wall-brick sense: detect a power-only USB-C charger through a single `220 kΩ` series resistor from `5V` (`VBUS`) to `D2` (`GPIO3` / `ADC1_CH2`) sampled against internal `45 kΩ` `INPUT_PULLDOWN`, so `preroll_mode: "usb_host"` also applies on a wall adapter while keeping `D2 >= 2.74 V` on battery | Ryan, #gotchi 2026-10-19 16:04 and 16:14; Amos & Zero voltage audit | Built in firmware, merged (PR #50 + PR #10 refinement); not measured on hardware |

## 5. Limits of today's build

- Maximum recording length: 120 s (`cfg.ptt_max_ms` default `120000` ms, `3.84 MB` WAV buffer in 8 MB PSRAM).
- Recordings shorter than `250 ms` (`cfg.ptt_min_ms`) or quieter than `50 LSB` RMS (`cfg.ptt_min_rms_lsb`) are discarded on-device; reference gateway additionally filters `< 400 ms` voiced clips and Whisper ghost phrases (`backend/voice_gateway.py`).
- Largest single reply event the firmware can read: 256 KB. The gateway sends about 11 KB per event, so reply length is not limited.
- Partial e-paper refresh about 0.3 s, full refresh 6.4 s measured on the 7.5 in bench panel (the 1.54 in figures are unmeasured on bench hardware).

## 5a. Timings and defaults

Confirmed by Ryan (#gotchi 2026-10-19 09:15): hybrid button behaviour, 120 s recording cap, 3 s snapshot attach window, and "the other timings you mentioned are good" (1.5 s trailing silence, 250 ms minimum press). Each is a `set_config` value.

- Hybrid: holding longer than 500 ms sends on release; a quick tap latches and auto-uploads after 1.5 s of trailing silence or a second tap.
- Recording cap 120 s (about 3.84 MB of the 8 MB PSRAM); 250 ms minimum press.
- Snapshot attach window 3 s, with a configurable `default_image_prompt` for a standalone snapshot.
- Pre-roll default: `preroll_mode: "usb_host"` (active when connected to either a USB data host or a 5V USB-C wall brick via F23; configurable to `"always"` or `"off"`).

## 5b. Go Live mode (F19)

Ryan wants the unit to support a live voice session, with the setting under Mike's control (Ryan, #gotchi 2026-10-19 09:35). The unit opens a WebSocket (`/api/live/ws`) to the gateway, streaming 16 kHz PCM audio up and playing 24 kHz PCM audio down. Estimated battery draw for continuous streaming is 110 to 140 mA (about 7 to 8 hours on the 1000 mAh battery; unmeasured on hardware).

- Off by default (`live_mode = false`). A `set_config` setting turns it on.
- Start: double-tap the top button within `double_tap_ms` (400 ms default), or say "Go Live" as the whole utterance (F21).
- End: press the top button during a session, or 15 seconds of silence (`live_silence_ms`).
- Mid-session camera support: pressing the bottom button (short press single snapshot or long press 5-photo burst) during a Live session injects base64 JPEG frames into the active WebSocket session (`firmware/src/live_client.cpp`).
- Customizable LLM Provider (`backend/llm_config.py`): Mike approved a metered API for Go Live on 2026-10-19 14:02 PT (#gotchi) on condition that the LLM configuration is user-customizable (`mock`, metered `api_key`, or `subscription` account bridge via `GET/PUT/POST /api/config/llm`).

## 5c. Lessons carried over from Mirrormere and the household voice work

Source: Mike, #gotchi 2026-10-19 14:23. Facts below come from `services/mirrormere-voice-gateway/gateway.py`, `specs/2026-10-02-lammen-voice-pipeline.md`, `specs/2026-10-16-gap-fill-topical-openers.md` and the ear client config in `specs/2026-10-16-ear-bargein-merge/`.

- **Spoken filler while the brain thinks:** Implemented in `backend/voice_gateway.py` (`filler_first_ms = 1200`, `filler_second_ms = 5000`, PR #36).
- **First sentence plays first:** Per-sentence `tts_synthesizer` streaming hook implemented in `backend/voice_gateway.py` (PR #36); wiring to real Whisper STT & Kokoro TTS backends is tracked in `docs/TASKS.md` T6.4 (Issue #40).
- **Cap spoken reply length:** Implemented via configurable `reply_cap_words = 60` in `backend/voice_gateway.py` (PR #36).
- **Filter speech-to-text ghosts:** Implemented in `backend/voice_gateway.py` (`min_voiced_ms = 400` + known Whisper hallucination phrase filter, PR #36).
- **Silence length:** `vad_silence_ms` defaults to Ryan's confirmed `1500 ms` (`1.5 s`); bench comparison against `800 ms`, `1.0 s`, and `ESP-SR` neural VAD is tracked in `docs/TASKS.md` T6.2 (Issue #38).
- **Barge-in (updated, Mike #gotchi 2026-10-19 14:25; Ryan 14:43):** Normal push-to-talk has no barge-in (`BTN_TOP` cancels/mutes playback). Inside Go Live only, a 64-tap NLMS adaptive echo canceller and 300 ms speech barge-in are implemented (PR #46) and gated behind `live_barge_in = false` by default (PR #47) until physical speaker-to-mic DMA delay is measured on the bench (`docs/TASKS.md` T6.1 / Issue #37).
- **Per-turn timing log & `node_id` validation:** Structured per-turn latency logging (`stt_ms`, `first_text_ms`, `first_audio_ms`, `total_ms`) and `^[A-Za-z0-9_-]{1,64}$` `node_id` validation are implemented on both gateway (PR #36) and firmware (PR #46 / Issue #39).

## 6. Open items & Bench Verification Checks

Questions for people:
- **Where the off-LAN gateway runs** (T3.2). Mike's call.
- **Wake word** is deferred to V1.1 (`docs/TASKS.md` T5.2). Confirm with Mike that it stays out of V1. Ryan's 24-hour battery target only applies once it ships.

Checks the robots owe:
- **Mirrormere room gateway image handler:** Checked 2026-10-19 in `services/mirrormere-voice-gateway/gateway.py` (read, not run against the live gateway): while `backend/voice_gateway.py` in this repo parses `image` and `image_0..4` burst parts, the Mirrormere room gateway splits every multipart part, takes `audio`, and decodes all other parts as text fields. Attaching a snapshot against Mirrormere needs a gateway change (Amos / Zero).
- **`D2` and `D4` idle voltage verification (Amos + Zero audit, resolved in code & queued for bench check):** Per the ESP32-S3 Datasheet (Section 5.4, Table 5-4 DC Characteristics, v2.2 at `VDD = 3.3V`), internal weak pull-up/pull-down resistance is `R_PU = R_PD = 45 kΩ` typical and digital high threshold is `V_IH_min = 0.75 × VDD = 2.475 V`. With two `220 kΩ` resistors on `D2`, if the `5V` (`VBUS`) rail is pulled to `0V` (`GND`) by the `MAX98357A` load when unplugged, both `220 kΩ` resistors sit in parallel to ground (`110 kΩ`), dropping `D2` to `3.3V × 110 / (45 + 110) = 2.34 V` (`< 2.475 V` `V_IH_min`). **Fix applied:** `D2` omits the external ground resistor and uses a **single `220 kΩ` series resistor from `5V` (`VBUS`) to `D2`** (`3x 220 kΩ` total across the build). In normal operation (`INPUT_PULLUP` `45 kΩ` to `3.3V`), even with `5V` at `0V`, `D2` idles at `3.3V × 220 / (45 + 220) = 2.74 V` (or `3.30 V` if `5V` floats), safely above `2.475 V`. During the `200 µs` 1 Hz `VBUS` sample, firmware enables `INPUT_PULLDOWN` (`45 kΩ` to `GND`) so `5V` wall power reads `5.0V × 45 / (220 + 45) ≈ 849 mV` (`>= 450 mV` threshold) vs. `0 mV` on battery. Bench-measure `D2` and `D4` idle voltages on the first assembled unit to confirm.

## 7. Out of scope for V1

- iOS BLE relay is not prioritised (Mike).
- Continuous wake-word / tiny audio-intent classifier is V1.1 (`docs/TASKS.md` T5.2).
- V2 hardware upgrades (`V2.1` ambient listening LED glow, `V2.2` `OV5640` 5MP autofocus camera, `V2.3` `<100 µA` neural wake co-processor, `V2.4` `MAX17048` I2C fuel gauge IC on `V2.5` custom carrier PCB & magnetic dock) are tracked in `docs/TASKS.md`.
