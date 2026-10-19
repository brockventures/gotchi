# Mirrormere voice client spec and e-ink audit (T3.1, T2.6)

Sources read 2026-10-18 in `azylman/mirrormere` at `8bcb2ca`: `api/openapi.yaml`,
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

## 2. Auth and remote access (T3.2): gap, no implementation here

The OpenAPI contract has no device token or auth scheme. The hub is LAN-only today.
Hotspot or BLE-relayed traffic therefore needs a gateway in front of the hub that checks a
per-device bearer token. The hub is another repo (`azylman/mirrormere`) that keeps its core
generic, so the gateway belongs in this repo or in deployment config, not in that core.
Not built. Decide where it runs before building.

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
