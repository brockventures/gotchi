# GOTCHI / SPRITE: Product Requirements (V1 draft)

Status: draft for Ryan and Mike to correct. Every requirement names its source. A line marked **OPEN** is a decision nobody has made; nothing in this file was invented to fill a gap. Current firmware values are listed as limits of today's build, not as requirements.

## 1. Goal

A pocket e-ink companion. The user holds a button and speaks. The device sends the speech to the Mirrormere hub and plays the spoken reply, showing a character face that reflects what it is doing.

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
| F13 | Pressing a button while a reply plays interrupts it; the bottom button can also cancel or mute playback | Ryan, #gotchi 2026-10-19 09:09 | Not built |
| F14 | A snapshot attaches to the next voice prompt if that prompt starts within a debounce time; otherwise it is sent alone for the bot to comment on | Ryan, #gotchi 2026-10-19 09:09 | Not built |
| F15 | Each unit points `voice_url` at its own backend; Ryan's unit goes straight to Zero's gateway | Ryan, #gotchi 2026-10-19 09:09 | Config exists (`voice_url`) |
| F16 | Battery life with normal usage: 48 hours without wake word, 24 hours with wake word enabled | Ryan, #gotchi 2026-10-19 09:18 | Not measured. Normal usage: 20 push-to-talk turns a day (Ryan, #gotchi 2026-10-19 09:21) |
| F17 | Hotspot test: from a cold start on a phone hotspot, one push-to-talk turn completes and the reply plays | Proposed by Amos, accepted by Ryan, #gotchi 2026-10-19 09:21 | Not tested |
| F18 | BLE relay test: the same turn with the phone away from home Wi-Fi | Proposed by Amos, accepted by Ryan, #gotchi 2026-10-19 09:21 | Not tested |
| F10 | First-boot Wi-Fi setup by QR code and captive portal | `docs/TASKS.md` T2.7 | Built, unflashed |

## 5. Limits of today's build

These are what the firmware does now. None is a decision.

- Maximum recording length: 15 s (F11 raises it) (`PTT_MAX_MS` in `main.cpp`, WAV buffer sized to match).
- Recordings shorter than 16,000 bytes or quieter than 50 LSB RMS are discarded and not uploaded. Ryan accepts a 0.25 s floor if the button-hold behaviour stays (Ryan, #gotchi 2026-10-19 09:09).
- Largest single reply event the firmware can read: 256 KB. The gateway sends about 11 KB per event, so reply length is not limited.
- Partial e-paper refresh about 0.3 s, full refresh 6.4 s measured on the 7.5 in bench panel (the 1.54 in figures are unmeasured).

## 5a. Default values chosen by Amos and Zero

Ryan asked for the longest recording the hardware supports, a configurable snapshot behaviour and a USB-only pre-roll default with a toggle, and left the numbers to us (#gotchi 2026-10-19 09:09 and 09:22). These are the defaults. Each is a `set_config` value, so changing one needs no new firmware. They are not Ryan's or Mike's decisions.

- Tap to start, auto-upload after about 1.5 s of trailing silence or a second tap; holding longer than 500 ms still sends on release.
- Recording cap 90 to 120 s (about 2.9 to 3.8 MB of the 8 MB PSRAM); 250 ms minimum press.
- `preroll_mode`: `usb_only` (default), `always`, `off`. Detecting USB power would use a VBUS sense input; whether the XIAO ESP32S3 Sense exposes one is unchecked.
- Snapshot attach window about 10 s, with a configurable `default_image_prompt` for a standalone snapshot.

## 6. Open items

Questions for people:
- **Where the off-LAN gateway runs** (T3.2). Mike's call.
- **Wake word** is deferred to V1.1 (`docs/TASKS.md` T5.2). Confirm with Mike that it stays out of V1. Ryan's 24-hour battery target only applies once it ships.

Checks the robots owe:
- Checked 2026-10-19 in `services/mirrormere-voice-gateway/gateway.py` (read, not run against the live gateway): the turn handler splits every multipart part, takes `audio`, and decodes all other parts as text fields. An `image` part would not fail the request, but nothing reads it, so attaching a snapshot needs a gateway change (Amos).
- Whether the XIAO ESP32S3 Sense exposes a USB-power sense pin (Zero).

## 7. Out of scope for V1

Nothing is here by decision yet except what the sources above state: iOS relay is not prioritised (Mike), wake word is V1.1 (`docs/TASKS.md` T5.2).
