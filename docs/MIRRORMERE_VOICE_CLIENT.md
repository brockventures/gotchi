# GOTCHI Voice Wire-Format Reference & E-Ink Refresh Notes (T3.1, T2.6)

> **Scope Note:** GOTCHI's backend is its own `backend/voice_gateway.py` (with each unit pointing `voice_url` at its configured gateway, e.g. `http://gotchi.local:8765/api/voice/interact`). Mirrormere (`azylman/mirrormere`) served strictly as a design inspiration and wire-format / e-ink refresh reference—never as GOTCHI's runtime backend.

Sources read 2026-10-18 in `azylman/mirrormere` at `8bcb2ca` for wire-format & e-ink inspiration: `api/openapi.yaml`,
`internal/voice/hub.go`, `internal/voice/coordinator.go`, `internal/server/voice.go`,
`client/eink-node/`. File and line facts below come from those; anything else is marked unchecked.

## 1. `POST /api/voice/interact`

Request: `multipart/form-data`.

| Field | Required | Value |
|---|---|---|
| `audio` | yes | 16 kHz mono PCM WAV |
| `node_id` | no | device id |
| `session_id` | no | correlation id |

Response: `200 text/event-stream`. Errors before the stream starts are JSON:

| Status | Meaning | Device action |
|---|---|---|
| 400 | bad or missing audio | drop the clip, show error sprite |
| 409 | another interaction in flight | show busy sprite, do not retry at once |
| 500 | pipeline error | show error sprite |
| 503 | hub disabled or inference worker down | show offline sprite, back off |

### SSE events (from `internal/voice/hub.go`)

There is **no `sprite_state` event** (`docs/TASKS.md` T3.1 names one). Derive sprite state on the device.

| Event | Data | Sprite use |
|---|---|---|
| `state` | `{"state": "<name>"}` | `listening`, `transcribing`, `thinking`, `synthesizing`, `speaking`, `idle`, `error` (`coordinator.go`). The hub emits `transcribing` on this stream; map the rest by name. |
| `transcript` | `{"transcript", "speaker"}` | `speaker` is empty when speaker matching is off or found nobody |
| `status` | `{"status"}` | brain progress text |
| `thinking` | `{"elapsed_seconds"}` | thinking animation tick |
| `reply` | `{"reply", "tts_engine"}` | reply text |
| `audio_chunk` | `{"chunk_index", "format":"pcm", "sample_rate", "channels", "is_final", "data"}` | `data` is base64 PCM; `sample_rate` defaults to 24000 |
| `error` | `{"error", "message"}` | `stt_error`, `brain_error`, `brain_timeout`, `tts_error` seen in code |
| `done` | `{"duration_ms"}` | end of stream, return to idle |

### Device client loop

```text
hold PTT -> record 16 kHz mono 16-bit PCM -> wrap as WAV (44-byte header)
POST /api/voice/interact (multipart, node_id = device id)
read SSE lines: "event: <name>" then "data: <json>", blank line ends a block
on audio_chunk: base64-decode, queue to I2S; honour sample_rate per chunk
on done: drain I2S queue, show idle sprite
on error or HTTP error: show error sprite, keep the clip out of the retry path
```

Memory note (unchecked on hardware): the 8 MB PSRAM should hold a few seconds of 16-bit 16 kHz audio (32 KB/s).

## 2. Auth and remote access (T3.2)

Per-device bearer token authentication (`Authorization: Bearer <token>`) and admin configuration auth (`X-Gotchi-Admin-Token` / `GOTCHI_ADMIN_TOKEN`) are implemented directly in GOTCHI's `backend/gateway_auth.py` and `backend/voice_gateway.py`.

## 3. `client/eink-node` audit (T2.6)

The tree is `client/eink-node/` (singular), a Python daemon; `AGENTS.md` and the stale
`clients/` directory use the old path. It targets a Waveshare **7.5" V2** panel through an
Adafruit bonnet on a Raspberry Pi (`panel.py`, `driver/epd7in5_V2.py`). It is not code for
the 1.54" SSD1681 and cannot be reused as is. The ideas below carry over:

- **Refresh policy** (`PanelManager.write_frame`): full refresh on first frame, after
  `max_consecutive_partials` partials, or after `full_refresh_minutes`; a failed partial
  recovers with a full refresh. Copy this policy into the firmware. Panel-specific numbers
  in the code are 7.5": full about 2.5 s, partial about 0.4 s. The 0.3 s figure for the
  1.54" panel is unmeasured.
- **Bounded BUSY wait** (`_read_busy`, 30 s timeout): the stock Waveshare loop can spin forever. Do the same in firmware.
- **Deep sleep after every write**: it clears controller RAM, so a partial refresh must reload the previous frame first (`WaveshareEPDPanel` docstring). `GxEPD2` handles this for the 1.54" class; verify in bring-up.
- **Event filtering** (`sse.py`): `voice.state` is in `IGNORED_EVENTS` there so voice does not flash the panel. A device that is itself the voice node needs the opposite choice; it must redraw on its own state.
- **Buttons** (`buttons.py`): GPIO 5 and 6 are Raspberry Pi pins in that daemon; nothing carries over.

## 4. GOTCHI Gateway Endpoint & `sentence` Event Contract

GOTCHI's `backend/voice_gateway.py` implements the SSE wire contract below. Each unit takes its target address from `voice_url` (`set_config`).

- **Endpoint:** `POST http://<gotchi-gateway>:8765/api/voice/interact` (`backend/voice_gateway.py`). The firmware default `voice_url` is `http://gotchi.local:8765/api/voice/interact`.
- **Request:** `multipart/form-data` with `audio` (`ptt.wav`, `audio/wav`, 16 kHz mono 16-bit WAV), `node_id`, `session_id` (plus optional `image` or `image_0`..`image_4` and `prompt`).
- **Response:** `200 text/event-stream`.

Events seen in live turns (order not recorded):

| Event | Data | Notes |
|---|---|---|
| `turn` | payload not recorded | Turn bookkeeping. Clients ignore it. |
| `state` | `{"state": "transcribing"}` etc. | Same state names as section 1. |
| `transcript` | `{"text", "transcript", "speaker"}` | Both `text` and `transcript` are present. |
| `status` | `{"status"}` | Brain progress text. |
| `sentence` | see below | Audio. Up to about 14 per turn. |
| `reply` | `{"reply"}` | Full reply text. |
| `done` | `{"duration_ms"}` | End of stream. |

Legacy `audio_chunk` (`{"sample_rate", "data", "is_final"}`) and `error` (`{"error", "message"}`) may also appear.
**There is no `audio_chunk` in live turns.** The audio is in `sentence.audio_b64`.

`sentence` shape:

```json
{"text": "...", "engine": "<name>", "format": "pcm", "sample_rate": 24000, "channels": 1, "audio_b64": "<base64 PCM16 LE>"}
```

Decode `audio_b64` as 16-bit signed little-endian mono PCM at `sample_rate`. Each `sentence` is described as "large" in the live check; sizes were not measured. The firmware parses it without copying the string. Its 256 KB line buffer is the known limit below.

Pre-stream errors are JSON with an HTTP status:

| Status | Device state |
|---|---|
| 400 | `error` (bad audio) |
| 409 | `busy` |
| 500 | `error` |
| 503 | `offline` |

Firmware (`firmware/src/voice_client.cpp`) implements this contract. It uses HTTP/1.1 with `Connection: close`, de-chunks `Transfer-Encoding: chunked` before splitting SSE lines, and drops any SSE line over 256 KB with a Serial message. Such a line is a sentence of about 4 s or more of 24 kHz audio, so the limit is a known gap.
