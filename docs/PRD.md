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
| F10 | First-boot Wi-Fi setup by QR code and captive portal | `docs/TASKS.md` T2.7 | Built, unflashed |

## 5. Limits of today's build

These are what the firmware does now. None is a decision.

- Maximum recording length: 15 s (F11 raises it) (`PTT_MAX_MS` in `main.cpp`, WAV buffer sized to match).
- Recordings shorter than 16,000 bytes or quieter than 50 LSB RMS are discarded and not uploaded. Ryan accepts a 0.25 s floor if the button-hold behaviour stays (Ryan, #gotchi 2026-10-19 09:09).
- Largest single reply event the firmware can read: 256 KB. The gateway sends about 11 KB per event, so reply length is not limited.
- Partial e-paper refresh about 0.3 s, full refresh 6.4 s measured on the 7.5 in bench panel (the 1.54 in figures are unmeasured).

## 6. Open requirements (need Ryan or Mike)

- **OPEN: hands-free listening.** Ryan asked whether one press could open listening and keep recording until he stops talking. That needs end-of-speech detection on the device. What silence length ends a turn, and what is the longest a turn may run? Proposal: 1.0 s of silence, with the longest recording the memory allows.
- **OPEN: standalone snapshot.** How long is the window in which a snapshot attaches to the next voice prompt? What should the bot do with a snapshot that arrives alone? Attaching needs an optional `image` field on `/api/voice/interact`; whether the gateway accepts one has not been checked.
- **OPEN: pre-roll purpose.** Ryan asked whether pre-roll is only for wake word. With push-to-talk it also catches the first syllables spoken before the chime and screen draw finish; Zero's mic task (PR #9) now covers part of that. Is a USB-only default still wanted?
- **OPEN: where the off-LAN gateway runs** (T3.2). Mike's call.
- **OPEN: hotspot and BLE modes** are in scope for V1, but no pass criteria exist.
- **OPEN: target battery life** and whether deep sleep is required for V1.
- **OPEN: wake word** is deferred to V1.1 (T5.2); confirm that stays out of V1.

## 7. Out of scope for V1

Nothing is here by decision yet except what the sources above state: iOS relay is not prioritised (Mike), wake word is V1.1 (`docs/TASKS.md` T5.2).
