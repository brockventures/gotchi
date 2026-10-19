# GOTCHI / SPRITE: Product Requirements (V1 draft)

Status: draft for Ryan and Mike to correct. Every requirement names its source. A line marked **OPEN** is a decision nobody has made; nothing in this file was invented to fill a gap. Current firmware values are listed as limits of today's build, not as requirements.

## 1. Goal

A pocket e-ink companion. The user holds a button and speaks. The device sends the speech to a voice backend over the Mirrormere wire protocol and plays the spoken reply, showing a character face that reflects what it is doing.

GOTCHI uses no Mirrormere hardware. The Pi Zero panel and the Pi gateway on the bench may be used to test software, and for nothing else; the locked V1 bill of materials is the hardware goal, changed only by what testing shows (Mike, #gotchi 2026-10-19 09:27 and 09:29). Which backend a unit talks to is set per unit with `voice_url`.

Sources: `README.md`; Mike and Ryan in #gotchi, 2026-10-18.

## 2. Users and contexts

- Mike and Ryan, one unit each for V1 (`docs/BOM.md`).
- Desk use first. Wearable form factor comes after the tech works (Mike, #gotchi 2026-10-18 22:08).
- Connectivity: home Wi-Fi and phone hotspot. Android BLE relay stays in scope (Ryan); iOS is not prioritised (Mike).

## 3. Core flow: one push-to-talk turn

1. User holds the top button. Device records and shows LISTENING.
2. User releases. Device uploads the recording and shows TRANSCRIBING.
3. Hub streams events. Device shows THINKING or SYNTHESIZING, then plays audio as it arrives and shows SPEAKING.
4. Stream ends. Device returns to IDLE.

Source: `docs/MIRRORMERE_VOICE_CLIENT.md`, `firmware/src/main.cpp`.

## 4. Functional requirements

| ID | Requirement | Source | Status |
|---|---|---|---|
| F1 | Push-to-talk is the primary input | Mike and Ryan, #gotchi | Built, unflashed |
| F2 | 500 ms pre-roll so the start of speech is not lost | `docs/TASKS.md` T2.3 | Built, unflashed |
| F3 | Reply audio plays as it streams, with no limit on reply length | This draft, from Ryan #gotchi 2026-10-19 08:56 | Built: gateway streams about 11 KB chunks, measured live 2026-10-19 |
| F4 | Nine on-screen states: idle, listening, transcribing, thinking, synthesizing, speaking, error, busy, offline | `firmware/include/ui_state.h` | Built, verified on a bench panel |
| F5 | Two skins, `zero` (default) and `gotchi`, set with `set_config` | Zero, PR #9 | Built, unflashed |
| F6 | Configuration over USB serial and Wi-Fi JSON-RPC | `README.md` section 3 | Partly built; `get_logs` is not built |
| F7 | Optional bearer token on Wi-Fi RPC and on hub requests | `docs/TASKS.md` T3.2 | Device side built; gateway side OPEN (see section 6) |
| F8 | Reply audio routing: speaker, Discord voice, BLE phone | `docs/TASKS.md` T3.3 | Not built |
| F9 | Camera snapshot on the bottom button | `README.md` | Camera driver built; snapshot flow not built |
| F11 | Recording cap raised to the longest the hardware reasonably supports | Ryan, #gotchi 2026-10-19 09:09 | Not built (15 s today) |
| F12 | Pre-roll runs on USB power by default, with a setting to keep it on at all times | Ryan, #gotchi 2026-10-19 09:09 | Not built |
| F13 | Top button is for speaking only. While a reply plays, pressing it cancels or mutes the reply and returns to idle. It does not start a new recording | Ryan, #gotchi 2026-10-19 09:45 | Built, unflashed (PR #12, the new button layout) |
| F14 | Bottom button is for the camera only. A short press takes a snapshot that attaches to the next voice prompt if that prompt starts within the attach window; otherwise it is sent alone for the bot to comment on. The bottom button no longer cancels a recording. A short press during a recording takes a snapshot and attaches it to the turn in progress (Ryan, #gotchi 2026-10-19 09:47) | Ryan, #gotchi 2026-10-19 09:15 and 09:45 | Built, unflashed (PR #12, the new button layout) |
| F15 | Each unit points `voice_url` at its own backend; Ryan's unit goes straight to Zero's gateway | Ryan, #gotchi 2026-10-19 09:09 | Config exists (`voice_url`) |
| F16 | Battery life with normal usage: 48 hours without wake word, 24 hours with wake word enabled | Ryan, #gotchi 2026-10-19 09:18 | Not measured. Normal usage: 20 push-to-talk turns a day (Ryan, #gotchi 2026-10-19 09:21) |
| F17 | Hotspot test: from a cold start on a phone hotspot, one push-to-talk turn completes and the reply plays | Proposed by Amos, accepted by Ryan, #gotchi 2026-10-19 09:21 | Not tested |
| F18 | BLE relay test: the same turn with the phone away from home Wi-Fi | Proposed by Amos, accepted by Ryan, #gotchi 2026-10-19 09:21 | Not tested |
| F19 | "Go Live" mode: a continuous two-way voice session through a live multimodal model, entered on purpose and ending on a timeout. Configurable so it can be turned off | Ryan, #gotchi 2026-10-19 09:21 and 09:35 | Placeholder only: the session shows a screen and times out, and connects to nothing |
| F20 | Long press on the bottom button takes a burst of five photos over 3 seconds and sends them together, for something moving or being turned between frames | Ryan, #gotchi 2026-10-19 09:45 | Photos are captured into memory (PR #12, the new button layout); the gateway reads no image today, so nothing is sent |
| F21 | Saying "Go Live" as a voice command starts a Live session | Ryan, #gotchi 2026-10-19 09:45 | Phrase match built, unflashed; the session it starts is a placeholder |
| F10 | First-boot Wi-Fi setup by QR code and captive portal | `docs/TASKS.md` T2.7 | Built, unflashed |

## 5. Limits of today's build

These are what the firmware does now. None is a decision.

- Maximum recording length: 15 s (F11 raises it) (`PTT_MAX_MS` in `main.cpp`, WAV buffer sized to match).
- Recordings shorter than 16,000 bytes or quieter than 50 LSB RMS are discarded and not uploaded. Ryan accepts a 0.25 s floor if the button-hold behaviour stays (Ryan, #gotchi 2026-10-19 09:09).
- Largest single reply event the firmware can read: 256 KB. The gateway sends about 11 KB per event, so reply length is not limited.
- Partial e-paper refresh about 0.3 s, full refresh 6.4 s measured on the 7.5 in bench panel (the 1.54 in figures are unmeasured).

## 5a. Timings and defaults

Confirmed by Ryan (#gotchi 2026-10-19 09:15): hybrid button behaviour, 120 s recording cap, 3 s snapshot attach window, and "the other timings you mentioned are good" (1.5 s trailing silence, 250 ms minimum press). Each is a `set_config` value.

- Hybrid: holding longer than 500 ms sends on release; a quick tap latches and auto-uploads after 1.5 s of trailing silence or a second tap.
- Recording cap 120 s (about 3.8 MB of the 8 MB PSRAM); 250 ms minimum press.
- Snapshot attach window 3 s, with a configurable `default_image_prompt` for a standalone snapshot.

Not yet confirmed: the `preroll_mode` default (`usb_only`, `always` or `off`). See section 6.

## 5b. Go Live mode (F19)

Ryan wants the unit to support a live voice session, with the setting under Mike's control (Ryan, #gotchi 2026-10-19 09:35). Zero proposed a WebSocket from the unit to the gateway, which would hold the model session; the device streams 16 kHz audio up and plays 24 kHz audio down. Zero's battery figure for continuous streaming is 110 to 140 mA, about 7 to 8 hours on the 1000 mAh battery; it is an unmeasured estimate.

- Off by default. A `live_mode` setting turns it on.
- Start: double-tap the top button, or say "Go Live" (F21). Detail below.
- End: press the top button during a session, or 15 seconds of silence; the silence length is a setting (`live_silence_ms`).
- The double-tap shares the top button with tap-to-talk. A second tap within a short interval (proposed 400 ms, a setting) of the first release counts as a double-tap and discards the clip the first tap started. A later second tap still means "send now".
- "Go Live" is matched on the transcript, and only when it is the whole utterance, so a sentence that merely contains the words does not start a session.
- Proposed by Zero, not confirmed: a bottom-button press (single photo or five-photo burst) during a Live session sends those frames into the live session too.
- Google's Gemini Live API is the known option. It bills per token. Mike approved a metered API for Go Live on 2026-10-19 14:02 PT (#gotchi), on one condition: the LLM configuration must be user-customizable, so a metered API key works and his own subscription account can be hooked up instead. The provider is therefore a setting on the gateway, never hard-coded; `live_mode` stays off by default.
- Whether Claude offers an equivalent: a web search on 2026-10-19 found no official Anthropic realtime audio endpoint; the sources were low-quality third-party posts. Check Anthropic's own API docs before relying on this.

## 5c. Lessons carried over from Mirrormere and the household voice work

Source: Mike, #gotchi 2026-10-19 14:23. Facts below come from `services/mirrormere-voice-gateway/gateway.py`, `specs/2026-10-02-lammen-voice-pipeline.md`, `specs/2026-10-16-gap-fill-topical-openers.md` and the ear client config in `specs/2026-10-16-ear-bargein-merge/`. Marked "proposed" until Ryan or Mike accepts.

- **Spoken filler while the brain thinks (proposed).** The room gateway plays one short clip after 1200 ms with no audio, and one more after 5 s. Filler began 1250 to 2270 ms into a turn, on 36 of 73 recent turns. One GOTCHI turn measured on 2026-10-19 took 606 ms for speech-to-text, 4.8 s to the first reply text and 6.4 s to the first audio. The device already shows THINKING; the gateway should also send a short filler sentence, and the device should not time out before it arrives.
- **First sentence plays first (proposed).** Text-to-speech runs per sentence so audio starts at the first sentence, not the whole reply. The reference gateway must do the same once it has real speech output; today it returns silence.
- **Cap spoken reply length (proposed).** The room profile caps replies at 60 words. The measured GOTCHI turn spoke 19 s of audio for 325 characters, which costs battery and attention on a pocket device. Add a `reply_cap_words` setting.
- **Filter speech-to-text ghosts (proposed).** Whisper invents phrases from silence, so the gateway drops known ghost lines and clips with under 400 ms of voiced audio. The device's 250 ms floor and loudness check alone do not catch this.
- **Silence length.** The room ear ends a turn after 800 ms of silence, with a 10 s cap and a neural voice detector, chosen over a plain loudness threshold after false triggers. GOTCHI uses 1.5 s and loudness only. Both stay configurable; the 800 ms figure is the tested starting point.
- **No barge-in without echo cancellation.** The room ear keeps barge-in off by default, needs 300 ms of speech and a stricter threshold during playback because echo leaks through. GOTCHI has no echo cancellation and its speaker sits centimetres from the mic. This supports Ryan's decision to drop barge-in, and it is a hazard for Go Live (F19), where the mic streams while the speaker plays.
- **Per-turn timing log (proposed).** The room gateway writes one line per turn: speech-to-text time, first text, first audio, total. GOTCHI should log the same fields on the device and the gateway, and keep `node_id` to letters, digits, dash and underscore, 64 characters at most.
- **Tuning knobs stay config.** Mirrormere keeps filler delay, reply cap and silence length as settings. GOTCHI already does this for most timings.

## 6. Open items

Questions for people:
- **Go Live (F19):** Mike approved the metered model API on 2026-10-19 (user-configurable provider required). Still open: the default for `live_mode`.
- **Where the off-LAN gateway runs** (T3.2). Mike's call.
- **Wake word** is deferred to V1.1 (`docs/TASKS.md` T5.2). Confirm with Mike that it stays out of V1. Ryan's 24-hour battery target only applies once it ships.

Checks the robots owe:
- Checked 2026-10-19 in `services/mirrormere-voice-gateway/gateway.py` (read, not run against the live gateway): the turn handler splits every multipart part, takes `audio`, and decodes all other parts as text fields. An `image` part would not fail the request, but nothing reads it, so attaching a snapshot needs a gateway change (Amos).
- USB-power sense: Zero reads Seeed\'s schematic as showing no 5 V sense pin on the XIAO ESP32S3 Sense (unverified by Amos). All eleven GPIOs D0 to D10 are assigned in `pins.h`, so a software-only check can tell a computer on USB from battery but not a power-only wall adapter. Ryan to choose the `preroll_mode` default.

## 7. Out of scope for V1

Nothing is here by decision yet except what the sources above state: iOS relay is not prioritised (Mike), wake word is V1.1 (`docs/TASKS.md` T5.2).
