from pathlib import Path

from poc.gotchi_poc import parse_sse_stream

FIXTURE = Path(__file__).parent / "fixtures" / "sse_full_turn.txt"


def test_full_turn_fixture_ends_idle_with_audio():
    with FIXTURE.open(encoding="utf-8") as f:
        ui = parse_sse_stream(f)
    assert ui.state == "idle"
    assert ui.audio_bytes_received > 0
    assert ui.reply == "50 grams total."
    assert ui.transcript == "what is the weight of the device"
    assert ui.status_text == "DONE (1840ms)"
