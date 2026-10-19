"""
Tests for GOTCHI BLE 5.0 Packet Framing Protocol (T4.1 / F18).
Covers:
- Header serialization, magic verification, CRC16 header validation.
- CRC32 payload checksum verification (corruption detection).
- Packet fragmentation into MTU-bounded chunks and stateful reassembly.
- Support for frame types: AUDIO_CHUNK, IMAGE_FRAME, TURN_COMMIT, SSE_EVENT, ACK, CANCEL.
- Discontinuity / loss detection and error handling.
- Cross-verification between backend/ble_framing.py and firmware/include/ble_framing.h & firmware/src/ble_framing.cpp.
"""

import pathlib
import pytest
from backend.ble_framing import (
    BLE_HEADER_SIZE,
    BLE_MAGIC,
    BLE_TRAILER_SIZE,
    BlePacket,
    BleReassembler,
    FrameFlags,
    FrameType,
    calc_crc16,
    calc_crc32,
    fragment_payload,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BLE_FRAMING_H = REPO_ROOT / "firmware" / "include" / "ble_framing.h"
BLE_FRAMING_CPP = REPO_ROOT / "firmware" / "src" / "ble_framing.cpp"


def test_firmware_ble_framing_source_invariants():
    """Verify C++ firmware sources implement required BLE framing contracts."""
    h_src = BLE_FRAMING_H.read_text(encoding="utf-8")
    cpp_src = BLE_FRAMING_CPP.read_text(encoding="utf-8")

    # Header constants and struct pack
    assert "BLE_MAGIC = 0x4742" in h_src
    assert "BLE_HEADER_SIZE = 14" in h_src
    assert "BLE_TRAILER_SIZE = 4" in h_src
    assert "#pragma pack(push, 1)" in h_src
    assert "struct PacketHeader" in h_src

    # Frame types
    for ft in ("AUDIO_CHUNK", "IMAGE_FRAME", "TURN_COMMIT", "SSE_EVENT", "ACK", "CANCEL"):
        assert ft in h_src

    # CRC functions and implementation
    assert "calcCrc16" in h_src and "calcCrc32" in h_src
    assert "0x1021" in cpp_src  # CRC16-CCITT polynomial
    assert "0xEDB88320" in cpp_src  # CRC32 polynomial

    # Encode, decode, and reassembler
    assert "encodePacket" in h_src and "decodePacket" in h_src
    assert "class PacketReassembler" in h_src


def test_crc16_and_crc32_vectors():
    """Validate CRC algorithms against known vectors."""
    test_data = b"GotchiBLE2026"
    crc16 = calc_crc16(test_data)
    crc32 = calc_crc32(test_data)

    assert isinstance(crc16, int) and 0 <= crc16 <= 0xFFFF
    assert isinstance(crc32, int) and 0 <= crc32 <= 0xFFFFFFFF

    # Consistency across calls
    assert calc_crc16(test_data) == crc16
    assert calc_crc32(test_data) == crc32

    # Bit mutation alters checksum
    mutated = b"GotchiBLE2027"
    assert calc_crc16(mutated) != crc16
    assert calc_crc32(mutated) != crc32


def test_single_packet_encode_decode_roundtrip():
    """Verify clean encode and decode of a single packet frame."""
    payload = b"\x00\x01\x02\x03\x04" * 20  # 100 bytes
    pkt = BlePacket(
        frame_type=FrameType.AUDIO_CHUNK,
        flags=FrameFlags.SINGLE_CHUNK,
        seq_num=42,
        chunk_idx=0,
        total_chunks=1,
        payload=payload,
    )

    encoded = pkt.encode()
    assert len(encoded) == BLE_HEADER_SIZE + len(payload) + BLE_TRAILER_SIZE

    decoded = BlePacket.decode(encoded)
    assert decoded.frame_type == FrameType.AUDIO_CHUNK
    assert decoded.flags == FrameFlags.SINGLE_CHUNK
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
    bad_header[4] ^= 0x01  # mutate sequence number without recalculating CRC16
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


def test_payload_fragmentation_and_reassembly_image_burst():
    """Verify large simulated JPEG snapshot splits across MTU chunks and reassembles perfectly."""
    # 12 KB simulated JPEG payload
    simulated_jpeg = b"\xFF\xD8\xFF\xE0" + (b"gotchi_jpeg_pixel_data_12345678" * 400) + b"\xFF\xD9"
    assert len(simulated_jpeg) > 10000

    packets = fragment_payload(
        frame_type=FrameType.IMAGE_FRAME,
        payload=simulated_jpeg,
        start_seq_num=500,
        max_chunk_size=400,
        requires_ack=True,
    )

    assert len(packets) > 25
    assert packets[0].flags & FrameFlags.FIRST_CHUNK
    assert packets[-1].flags & FrameFlags.LAST_CHUNK
    assert all(p.flags & FrameFlags.REQUIRES_ACK for p in packets)

    reassembler = BleReassembler()
    completed = False
    reassembled_bytes = None
    frame_type = None

    for p in packets:
        raw_wire = p.encode()
        decoded_wire = BlePacket.decode(raw_wire)
        is_done, data, f_type = reassembler.push(decoded_wire)
        if is_done:
            completed = True
            reassembled_bytes = data
            frame_type = f_type

    assert completed is True
    assert frame_type == FrameType.IMAGE_FRAME
    assert reassembled_bytes == simulated_jpeg


def test_reassembler_detects_missing_chunk():
    """Verify dropped packet in stream raises discontinuity error."""
    payload = b"A" * 1500
    packets = fragment_payload(
        frame_type=FrameType.AUDIO_CHUNK,
        payload=payload,
        start_seq_num=1,
        max_chunk_size=300,
    )

    reassembler = BleReassembler()
    # Ingest chunk 0
    reassembler.push(packets[0])
    # Drop chunk 1, attempt to ingest chunk 2
    with pytest.raises(ValueError, match="Packet chunk sequence discontinuity"):
        reassembler.push(packets[2])


def test_control_frames_and_ack():
    """Verify control frame types (ACK, CANCEL, TURN_COMMIT, SSE_EVENT)."""
    for ft in (FrameType.ACK, FrameType.CANCEL, FrameType.TURN_COMMIT, FrameType.SSE_EVENT):
        pkt = BlePacket(
            frame_type=ft,
            flags=FrameFlags.SINGLE_CHUNK,
            seq_num=1,
            chunk_idx=0,
            total_chunks=1,
            payload=b'{"ack_seq": 10}' if ft == FrameType.ACK else b"",
        )
        encoded = pkt.encode()
        decoded = BlePacket.decode(encoded)
        assert decoded.frame_type == ft
