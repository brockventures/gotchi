import base64
import struct
from poc.gotchi_poc import (
    GotchiUIState,
    RefreshTracker,
    build_multipart_wav,
    parse_sse_stream,
    render_sprite_200x200,
    wrap_pcm16_to_wav,
)


def test_wrap_pcm16_to_wav_header():
    pcm = b"\x00\x00" * 16000  # 1.0s at 16 kHz mono 16-bit
    wav = wrap_pcm16_to_wav(pcm, sample_rate=16000, channels=1)
    assert len(wav) == 44 + len(pcm)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    sr, byte_rate = struct.unpack("<II", wav[24:32])
    assert sr == 16000
    assert byte_rate == 32000


def test_multipart_payload():
    wav = wrap_pcm16_to_wav(b"\x01\x02" * 100)
    body, ctype = build_multipart_wav(wav, node_id="gotchi-pi0", session_id="s-1")
    assert "multipart/form-data; boundary=" in ctype
    assert b'name="audio"; filename="ptt.wav"' in body
    assert b"gotchi-pi0" in body


def test_refresh_tracker_policy():
    rt = RefreshTracker(max_consecutive_partials=3, full_refresh_minutes=15.0)
    assert rt.select_refresh_mode(now=100.0) == "full"
    rt.record_write("full", now=100.0)
    assert rt.select_refresh_mode(now=101.0) == "partial"
    rt.record_write("partial", now=101.0)
    rt.record_write("partial", now=102.0)
    rt.record_write("partial", now=103.0)
    # Hit max_consecutive_partials (3) -> forces full refresh
    assert rt.select_refresh_mode(now=104.0) == "full"
    # Failed partial recovers with full
    assert rt.record_write("partial", succeeded=False, now=105.0) == "full"


def test_parse_sse_stream_and_render_sprite():
    raw_pcm = b"\x10\x00" * 240
    b64_pcm = base64.b64encode(raw_pcm).decode()
    sse_lines = [
        "event: state",
        'data: {"state": "transcribing"}',
        "",
        "event: transcript",
        'data: {"transcript": "Hello Gotchi", "speaker": "ryan"}',
        "",
        "event: thinking",
        'data: {"elapsed_seconds": 1}',
        "",
        "event: reply",
        'data: {"reply": "Loud and clear.", "tts_engine": "kokoro"}',
        "",
        "event: audio_chunk",
        f'data: {{"chunk_index": 0, "format": "pcm", "sample_rate": 24000, "channels": 1, "is_final": true, "data": "{b64_pcm}"}}',
        "",
        "event: done",
        'data: {"duration_ms": 840}',
        "",
    ]
    states_seen = []
    pcm_chunks = []
    ui = parse_sse_stream(
        sse_lines,
        on_state_change=lambda s: states_seen.append(s.state),
        on_audio_pcm=lambda pcm, sr, final: pcm_chunks.append((pcm, sr, final)),
    )
    assert ui.state == "idle"
    assert ui.transcript == "Hello Gotchi"
    assert ui.reply == "Loud and clear."
    assert len(pcm_chunks) == 1
    assert pcm_chunks[0][0] == raw_pcm
    assert pcm_chunks[0][1] == 24000
    assert pcm_chunks[0][2] is True

    im = render_sprite_200x200(ui, refresh_mode="partial")
    assert im.size == (200, 200)
    assert im.mode == "1"


def test_parse_sse_live_sentence_stream():
    # Live gateway shape (2026-10-18): turn, state, transcript, sentence x2, done.
    pcm_a = b"\x10\x00" * 300  # 600 bytes
    pcm_b = b"\x20\x00" * 50   # 100 bytes
    sse_lines = [
        "event: turn",
        'data: {"turn_id": "t-1"}',
        "",
        "event: state",
        'data: {"state": "transcribing"}',
        "",
        "event: transcript",
        'data: {"text": "hello", "transcript": "hello", "speaker": ""}',
        "",
        "event: state",
        'data: {"state": "speaking"}',
        "",
        "event: sentence",
        'data: {"text": "one", "engine": "kokoro", "format": "pcm", "sample_rate": 24000, '
        '"channels": 1, "audio_b64": "' + base64.b64encode(pcm_a).decode() + '"}',
        "",
        "event: sentence",
        'data: {"text": "two", "engine": "kokoro", "format": "pcm", "sample_rate": 24000, '
        '"channels": 1, "audio_b64": "' + base64.b64encode(pcm_b).decode() + '"}',
        "",
        "event: done",
        'data: {"duration_ms": 1234}',
        "",
    ]
    pcm_chunks = []
    ui = parse_sse_stream(sse_lines, on_audio_pcm=lambda pcm, sr, final: pcm_chunks.append((pcm, sr, final)))
    assert ui.audio_bytes_received == len(pcm_a) + len(pcm_b) == 700
    assert len(pcm_chunks) == 2
    assert pcm_chunks[0][0] == pcm_a and pcm_chunks[1][0] == pcm_b
    assert all(sr == 24000 and final is False for _, sr, final in pcm_chunks)
    assert ui.transcript == "hello"
    assert ui.state == "idle"  # `done` is the last state change
    assert ui.status_text == "DONE (1234ms)"
