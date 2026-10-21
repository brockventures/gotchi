"""
Tests for GOTCHI BLE 5.0 Packet Framing Protocol (T4.1 / F18).
Covers:
- 16-byte header serialization, magic verification, CRC16 header validation, and burst frame_index (0..4).
- CRC32 payload checksum verification (corruption detection).
- Packet fragmentation into MTU-bounded chunks and stateful reassembly.
- Strict sequence number (`seq_num`) and chunk index (`chunk_idx`) continuity enforcement.
- Cross-verification between backend/ble_framing.py and firmware/include/ble_framing.h & firmware/src/ble_framing.cpp
  (PSRAM allocation via ps_malloc, frame_index field, seq_num gap detection).
"""

import pathlib
import pytest
from backend.ble_framing import (
    ADPCM_HEADER_SIZE,
    ADPCM_MAGIC,
    BLE_HEADER_SIZE,
    BLE_MAGIC,
    BLE_TRAILER_SIZE,
    BlePacket,
    BleReassembler,
    FrameFlags,
    FrameType,
    calc_crc16,
    calc_crc32,
    decode_adpcm_to_wav,
    decode_ima_adpcm,
    encode_ima_adpcm,
    encode_ima_adpcm_with_state,
    encode_wav_to_adpcm,
    fragment_payload,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BLE_FRAMING_H = REPO_ROOT / "firmware" / "include" / "ble_framing.h"
BLE_FRAMING_CPP = REPO_ROOT / "firmware" / "src" / "ble_framing.cpp"
MAIN_CPP = REPO_ROOT / "firmware" / "src" / "main.cpp"
VOICE_CLIENT_CPP = REPO_ROOT / "firmware" / "src" / "voice_client.cpp"


def test_firmware_ble_framing_source_invariants():
    """Verify C++ firmware sources implement PSRAM allocation, frame_index, seq_num continuity, and main.cpp inclusion."""
    h_src = BLE_FRAMING_H.read_text(encoding="utf-8")
    cpp_src = BLE_FRAMING_CPP.read_text(encoding="utf-8")
    main_src = MAIN_CPP.read_text(encoding="utf-8")

    # Included in main.cpp so firmware build compiles ble_framing.h alongside main
    assert '#include "ble_framing.h"' in main_src

    # Header constants and struct pack (16 bytes with frame_index)
    assert "BLE_MAGIC = 0x4742" in h_src
    assert "BLE_HEADER_SIZE = 16" in h_src
    assert "BLE_TRAILER_SIZE = 4" in h_src
    assert "uint8_t  frame_index;" in h_src
    assert "#pragma pack(push, 1)" in h_src
    assert "struct PacketHeader" in h_src

    # PSRAM allocation via ps_malloc with error logging on failure
    assert "psramFound()" in cpp_src
    assert "ps_malloc(max_size_)" in cpp_src
    assert 'RingLogger.error("ble", "PacketReassembler buffer allocation failed")' in cpp_src

    # Sequence number continuity check across packets
    assert "if (has_last_seq_)" in cpp_src
    assert "if (hdr.seq_num != expected_seq)" in cpp_src

    # Burst frame_index consistency check
    assert "hdr.frame_index != current_frame_index_" in cpp_src

    # 4-bit IMA ADPCM Smart Pipe support in C++ firmware
    assert "ADPCM        = 0x08" in h_src
    assert "ADPCM_MAGIC = 0x31444147" in h_src
    assert "encodeWavToAdpcm" in h_src
    assert "decodeAdpcmToPcm" in h_src
    assert "encodeImaAdpcm" in cpp_src
    assert "decodeImaAdpcm" in cpp_src


def test_crc16_and_crc32_vectors():
    """Validate CRC16-CCITT and IEEE 802.3 CRC32 against standard "123456789" test vectors."""
    std_vec = b"123456789"
    assert calc_crc16(std_vec) == 0x29B1
    assert calc_crc32(std_vec) == 0xCBF43926

    test_data = b"GotchiBLE2026"
    crc16 = calc_crc16(test_data)
    crc32 = calc_crc32(test_data)
    assert crc16 == 0xD234

    mutated = b"GotchiBLE2027"
    assert calc_crc16(mutated) != crc16
    assert calc_crc32(mutated) != crc32


def test_single_packet_encode_decode_roundtrip_and_frame_index():
    """Verify clean encode and decode of a single packet frame including burst frame_index."""
    payload = b"\x00\x01\x02\x03\x04" * 20  # 100 bytes
    pkt = BlePacket(
        frame_type=FrameType.IMAGE_FRAME,
        flags=FrameFlags.SINGLE_CHUNK,
        seq_num=42,
        chunk_idx=0,
        total_chunks=1,
        payload=payload,
        frame_index=3,
    )

    encoded = pkt.encode()
    assert len(encoded) == BLE_HEADER_SIZE + len(payload) + BLE_TRAILER_SIZE

    decoded = BlePacket.decode(encoded)
    assert decoded.frame_type == FrameType.IMAGE_FRAME
    assert decoded.flags == FrameFlags.SINGLE_CHUNK
    assert decoded.frame_index == 3
    assert decoded.seq_num == 42
    assert decoded.chunk_idx == 0
    assert decoded.total_chunks == 1
    assert decoded.payload == payload


def test_decode_rejects_corrupted_header_or_payload():
    """Verify bit flips in header or payload trigger CRC validation errors."""
    payload = b"Hello, Mirrormere voice turn!"
    pkt = BlePacket(
        frame_type=FrameType.TURN_COMMIT,
        flags=FrameFlags.SINGLE_CHUNK,
        seq_num=101,
        chunk_idx=0,
        total_chunks=1,
        payload=payload,
    )
    raw = bytearray(pkt.encode())

    # 1. Corrupt magic
    bad_magic = bytearray(raw)
    bad_magic[0] ^= 0xFF
    with pytest.raises(ValueError, match="Invalid magic"):
        BlePacket.decode(bytes(bad_magic))

    # 2. Corrupt header byte (should fail CRC16)
    bad_header = bytearray(raw)
    bad_header[6] ^= 0x01  # mutate sequence number without recalculating CRC16
    with pytest.raises(ValueError, match="CRC16 mismatch"):
        BlePacket.decode(bytes(bad_header))

    # 3. Corrupt payload byte (should fail CRC32)
    bad_payload = bytearray(raw)
    bad_payload[BLE_HEADER_SIZE + 2] ^= 0x55
    with pytest.raises(ValueError, match="CRC32 mismatch"):
        BlePacket.decode(bytes(bad_payload))

    # 4. Truncated packet
    with pytest.raises(ValueError, match="too short|Truncated packet"):
        BlePacket.decode(raw[:10])


def test_payload_fragmentation_and_reassembly_5_photo_burst():
    """Verify 5-photo burst preserves distinct frame_index (0..4) across fragmented MTU chunks."""
    reassembler = BleReassembler()
    seq = 100
    reconstructed_burst = []

    for burst_idx in range(5):
        simulated_jpeg = b"\xFF\xD8\xFF\xE0" + (f"frame_{burst_idx}_".encode() * 300) + b"\xFF\xD9"
        packets = fragment_payload(
            frame_type=FrameType.IMAGE_FRAME,
            payload=simulated_jpeg,
            start_seq_num=seq,
            max_chunk_size=400,
            requires_ack=True,
            frame_index=burst_idx,
        )
        seq += len(packets)

        for p in packets:
            raw_wire = p.encode()
            decoded_wire = BlePacket.decode(raw_wire)
            assert decoded_wire.frame_index == burst_idx
            is_done, data, f_type = reassembler.push(decoded_wire)
            if is_done:
                reconstructed_burst.append((burst_idx, f_type, data))

    assert len(reconstructed_burst) == 5
    for idx, (b_idx, f_type, data) in enumerate(reconstructed_burst):
        assert b_idx == idx
        assert f_type == FrameType.IMAGE_FRAME
        assert f"frame_{idx}_".encode() in data


def test_reassembler_detects_seq_num_and_chunk_discontinuities():
    """Verify dropped packets or sequence number gaps raise discontinuity errors."""
    payload = b"A" * 1500
    packets = fragment_payload(
        frame_type=FrameType.AUDIO_CHUNK,
        payload=payload,
        start_seq_num=10,
        max_chunk_size=300,
    )

    # 1. Dropped chunk within a frame (seq_num jumps from 10 to 12)
    reassembler = BleReassembler()
    reassembler.push(packets[0])
    with pytest.raises(ValueError, match="sequence number discontinuity"):
        reassembler.push(packets[2])

    # 2. Dropped single-chunk frame between turns (chunk_idx is 0 on both, but seq_num jumps from 50 to 52)
    reassembler2 = BleReassembler()
    pkt1 = fragment_payload(FrameType.AUDIO_CHUNK, b"chunk1", start_seq_num=50)[0]
    pkt3 = fragment_payload(FrameType.AUDIO_CHUNK, b"chunk3", start_seq_num=52)[0]
    reassembler2.push(pkt1)
    with pytest.raises(ValueError, match="sequence number discontinuity"):
        reassembler2.push(pkt3)


def test_ima_adpcm_4x_compression_and_wav_roundtrip():
    """Verify 4-bit IMA ADPCM achieves 4:1 audio compression and preserves waveform fidelity."""
    import math
    import struct

    sample_rate = 16000
    num_samples = 1600  # 100 ms @ 16 kHz = 3,200 bytes PCM16
    orig_samples = [
        int(12000.0 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate)))
        for i in range(num_samples)
    ]
    pcm_bytes = struct.pack(f"<{num_samples}h", *orig_samples)

    adpcm_bytes = encode_ima_adpcm(pcm_bytes)
    assert len(adpcm_bytes) == num_samples // 2  # 800 bytes (exact 4:1 reduction vs 3,200 bytes)

    decoded_pcm = decode_ima_adpcm(adpcm_bytes, num_samples=num_samples)
    assert len(decoded_pcm) == len(pcm_bytes)
    decoded_samples = struct.unpack(f"<{num_samples}h", decoded_pcm)

    # Verify low reconstruction error after initial step adaptation
    mse = sum((a - b) ** 2 for a, b in zip(orig_samples[32:], decoded_samples[32:])) / (num_samples - 32)
    rmse = math.sqrt(mse)
    assert rmse < 650.0

    # Verify GAD1 container roundtrip to standard 44-byte RIFF WAV
    gad1_blob = encode_wav_to_adpcm(pcm_bytes, default_sample_rate=sample_rate)
    assert gad1_blob[:4] == ADPCM_MAGIC
    assert ADPCM_HEADER_SIZE == 16
    assert len(gad1_blob) == ADPCM_HEADER_SIZE + len(adpcm_bytes)

    wav_out = decode_adpcm_to_wav(gad1_blob)
    assert wav_out[:4] == b"RIFF"
    assert wav_out[8:12] == b"WAVE"
    assert len(wav_out) == 44 + len(pcm_bytes)

    # Verify non-zero-crossing chunk start has near-zero transient error thanks to GAD1 initial_predictor seeding
    non_zero_start_samples = [
        int(14000.0 * math.cos(2.0 * math.pi * 440.0 * (i / sample_rate)))
        for i in range(400)
    ]
    non_zero_pcm = struct.pack("<400h", *non_zero_start_samples)
    _, _, _, end_pred, end_step = encode_ima_adpcm_with_state(non_zero_pcm)
    gad1_non_zero = encode_wav_to_adpcm(non_zero_pcm, default_sample_rate=sample_rate)
    decoded_non_zero_wav = decode_adpcm_to_wav(gad1_non_zero)
    decoded_non_zero_samples = struct.unpack("<400h", decoded_non_zero_wav[44:])
    # Sample 0 starts at +14000; with initial_predictor seeded in the 16-byte GAD1 header, error on sample 0 is <= 8 LSB
    assert abs(non_zero_start_samples[0] - decoded_non_zero_samples[0]) <= 8

    # Verify stateful multi-chunk continuation across adjacent downlink chunks
    chunk2_samples = [
        int(14000.0 * math.cos(2.0 * math.pi * 440.0 * ((i + 400) / sample_rate)))
        for i in range(400)
    ]
    chunk2_pcm = struct.pack("<400h", *chunk2_samples)
    gad1_chunk2 = encode_wav_to_adpcm(
        chunk2_pcm,
        default_sample_rate=sample_rate,
        initial_predictor=end_pred,
        initial_step_index=end_step,
    )
    decoded_chunk2_wav = decode_adpcm_to_wav(gad1_chunk2)
    decoded_chunk2_samples = struct.unpack("<400h", decoded_chunk2_wav[44:])
    assert abs(chunk2_samples[0] - decoded_chunk2_samples[0]) < 250


def test_firmware_ble_out_of_range_failover_invariants():
    """Verify Gotchi cleanly fails over to Wi-Fi and onboard speaker when phone is out of BLE range."""
    vc_src = VOICE_CLIENT_CPP.read_text(encoding="utf-8")
    main_src = MAIN_CPP.read_text(encoding="utf-8")

    # 1. BLE-out-of-range Wi-Fi power restoration in main.cpp
    assert "manageBleLowPowerWiFi" in main_src
    assert "WiFi.mode(WIFI_STA)" in main_src

    # 2. Automatic audio_out_mode failover from ble_phone -> speaker when phone is disconnected
    assert 'String("speaker")' in vc_src
    assert 'const bool mute_local = (effective_audio_out_mode == "discord_voice" || effective_audio_out_mode == "ble_phone")' in vc_src

    # 3. Mid-turn BLE disconnect falls through to direct Wi-Fi HTTP upload when Wi-Fi is connected
    assert "BLE turn failed; failing over to direct Wi-Fi + onboard speaker" in vc_src
    assert "BLE journal send failed; falling back to Wi-Fi if connected" in vc_src


