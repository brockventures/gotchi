#!/usr/bin/env python3
"""
GOTCHI BLE 5.0 Packet Framing Protocol (T4.1 / F18) Reference Codec
====================================================================
Satisfies:
- Binary packet framing over BLE 5.0 2M PHY (GATT / L2CAP CoC).
- 16-byte packed header with magic (0x4742), frame_type, flags, burst frame_index (0..4),
  reserved byte, seq_num, chunk_idx, total_chunks, payload_len, and CRC16-CCITT check (14 bytes).
- 4-byte CRC32 payload validation trailer (IEEE 802.3, polynomial 0xEDB88320).
- Fragmentation into MTU-bounded chunks and stateful reassembly enforcing both
  chunk_idx and seq_num continuity.
"""

import enum
import struct
import zlib
from typing import List, Optional, Tuple

BLE_MAGIC = 0x4742  # 'GB' in little-endian
BLE_HEADER_SIZE = 16
BLE_TRAILER_SIZE = 4
BLE_DEFAULT_MTU = 512
BLE_MAX_CHUNK_PAYLOAD = BLE_DEFAULT_MTU - BLE_HEADER_SIZE - BLE_TRAILER_SIZE  # 492 bytes


class FrameType(enum.IntEnum):
    AUDIO_CHUNK = 0x01
    IMAGE_FRAME = 0x02
    TURN_COMMIT = 0x03
    SSE_EVENT   = 0x04
    ACK         = 0x05
    CANCEL      = 0x06


class FrameFlags(enum.IntFlag):
    NONE         = 0x00
    FIRST_CHUNK  = 0x01
    LAST_CHUNK   = 0x02
    SINGLE_CHUNK = 0x03  # FIRST | LAST
    REQUIRES_ACK = 0x04


def calc_crc16(data: bytes) -> int:
    """CRC16-CCITT (Polynomial 0x1021, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def calc_crc32(data: bytes) -> int:
    """Standard IEEE 802.3 CRC32."""
    return zlib.crc32(data) & 0xFFFFFFFF


class BlePacket:
    """Parsed BLE framing packet matching C++ gotchi_ble::PacketHeader."""

    def __init__(
        self,
        frame_type: FrameType,
        flags: FrameFlags,
        seq_num: int,
        chunk_idx: int,
        total_chunks: int,
        payload: bytes,
        frame_index: int = 0,
    ):
        self.frame_type = FrameType(frame_type)
        self.flags = FrameFlags(flags)
        self.frame_index = frame_index & 0xFF
        self.seq_num = seq_num & 0xFFFF
        self.chunk_idx = chunk_idx & 0xFFFF
        self.total_chunks = total_chunks & 0xFFFF
        self.payload = payload

    def encode(self) -> bytes:
        """Serializes packet into 16-byte header + payload + 4-byte CRC32 trailer."""
        payload_len = len(self.payload)
        header_prefix = struct.pack(
            "<HBBBBHHHH",
            BLE_MAGIC,
            int(self.frame_type),
            int(self.flags),
            self.frame_index,
            0,  # reserved
            self.seq_num,
            self.chunk_idx,
            self.total_chunks,
            payload_len,
        )
        crc16 = calc_crc16(header_prefix)
        header = header_prefix + struct.pack("<H", crc16)

        crc32 = calc_crc32(self.payload) if payload_len > 0 else 0
        trailer = struct.pack("<I", crc32)

        return header + self.payload + trailer

    @classmethod
    def decode(cls, raw: bytes) -> "BlePacket":
        """Deserializes and verifies a raw binary BLE frame."""
        if len(raw) < (BLE_HEADER_SIZE + BLE_TRAILER_SIZE):
            raise ValueError(f"Packet too short ({len(raw)} bytes; min {BLE_HEADER_SIZE + BLE_TRAILER_SIZE})")

        (
            magic,
            f_type,
            flags,
            frame_index,
            _reserved,
            seq_num,
            chunk_idx,
            total_chunks,
            payload_len,
            crc16,
        ) = struct.unpack("<HBBBBHHHHH", raw[:BLE_HEADER_SIZE])

        if magic != BLE_MAGIC:
            raise ValueError(f"Invalid magic 0x{magic:04X}; expected 0x{BLE_MAGIC:04X}")

        computed_crc16 = calc_crc16(raw[:14])
        if computed_crc16 != crc16:
            raise ValueError(f"CRC16 mismatch: received 0x{crc16:04X}, computed 0x{computed_crc16:04X}")

        expected_total = BLE_HEADER_SIZE + payload_len + BLE_TRAILER_SIZE
        if len(raw) < expected_total:
            raise ValueError(f"Truncated packet: expected {expected_total} bytes, got {len(raw)}")

        payload = raw[BLE_HEADER_SIZE : BLE_HEADER_SIZE + payload_len]
        trailer = raw[BLE_HEADER_SIZE + payload_len : expected_total]
        (crc32,) = struct.unpack("<I", trailer)

        computed_crc32 = calc_crc32(payload) if payload_len > 0 else 0
        if computed_crc32 != crc32:
            raise ValueError(f"CRC32 mismatch: received 0x{crc32:08X}, computed 0x{computed_crc32:08X}")

        return cls(
            frame_type=FrameType(f_type),
            flags=FrameFlags(flags),
            seq_num=seq_num,
            chunk_idx=chunk_idx,
            total_chunks=total_chunks,
            payload=payload,
            frame_index=frame_index,
        )


def fragment_payload(
    frame_type: FrameType,
    payload: bytes,
    start_seq_num: int = 1,
    max_chunk_size: int = BLE_MAX_CHUNK_PAYLOAD,
    requires_ack: bool = False,
    frame_index: int = 0,
) -> List[BlePacket]:
    """Splits a multi-byte payload into sequential MTU-bounded BlePacket instances."""
    if len(payload) == 0:
        flags = FrameFlags.SINGLE_CHUNK
        if requires_ack:
            flags |= FrameFlags.REQUIRES_ACK
        return [
            BlePacket(
                frame_type=frame_type,
                flags=flags,
                seq_num=start_seq_num,
                chunk_idx=0,
                total_chunks=1,
                payload=b"",
                frame_index=frame_index,
            )
        ]

    chunks = [payload[i : i + max_chunk_size] for i in range(0, len(payload), max_chunk_size)]
    total = len(chunks)
    packets = []

    for idx, chunk in enumerate(chunks):
        flags = FrameFlags.NONE
        if idx == 0:
            flags |= FrameFlags.FIRST_CHUNK
        if idx == total - 1:
            flags |= FrameFlags.LAST_CHUNK
        if requires_ack:
            flags |= FrameFlags.REQUIRES_ACK

        packet = BlePacket(
            frame_type=frame_type,
            flags=flags,
            seq_num=(start_seq_num + idx) & 0xFFFF,
            chunk_idx=idx,
            total_chunks=total,
            payload=chunk,
            frame_index=frame_index,
        )
        packets.append(packet)

    return packets


class BleReassembler:
    """Stateful stream defragmenter enforcing both chunk_idx and seq_num continuity."""

    def __init__(self, max_payload_bytes: int = 128 * 1024):
        self.max_payload_bytes = max_payload_bytes
        self.buffer = bytearray()
        self.current_type: Optional[FrameType] = None
        self.current_frame_index: int = 0
        self.expected_chunk: int = 0
        self.total_chunks: int = 0
        self.last_seq_num: Optional[int] = None
        self.in_progress: bool = False

    def reset(self):
        self.buffer.clear()
        self.current_type = None
        self.current_frame_index = 0
        self.expected_chunk = 0
        self.total_chunks = 0
        self.in_progress = False

    def reset_sequence_tracking(self):
        self.reset()
        self.last_seq_num = None

    def push(self, packet: BlePacket) -> Tuple[bool, Optional[bytes], Optional[FrameType]]:
        """
        Ingests a packet.
        Returns (is_complete, complete_payload_bytes, frame_type).
        Raises ValueError if seq_num or chunk_idx is discontinuous or corrupt.
        """
        if self.last_seq_num is not None:
            expected_seq = (self.last_seq_num + 1) & 0xFFFF
            if packet.seq_num != expected_seq:
                self.reset()
                self.last_seq_num = None
                raise ValueError(
                    f"Packet sequence number discontinuity: expected {expected_seq}, got {packet.seq_num}"
                )

        is_first = bool(packet.flags & FrameFlags.FIRST_CHUNK) or (packet.chunk_idx == 0)
        is_last = bool(packet.flags & FrameFlags.LAST_CHUNK) or (packet.chunk_idx + 1 == packet.total_chunks)

        if is_first:
            if self.in_progress:
                self.reset()
                raise ValueError("Incomplete multi-chunk frame interrupted by new FIRST_CHUNK")
            self.reset()
            self.current_type = packet.frame_type
            self.current_frame_index = packet.frame_index
            self.total_chunks = packet.total_chunks
            self.expected_chunk = 0
            self.in_progress = True
        elif not self.in_progress:
            raise ValueError(f"Received mid-stream packet (chunk {packet.chunk_idx}) without first chunk")

        if packet.chunk_idx != self.expected_chunk:
            seq_expected = self.expected_chunk
            self.reset()
            raise ValueError(f"Packet chunk sequence discontinuity: expected {seq_expected}, got {packet.chunk_idx}")

        if packet.frame_type != self.current_type or packet.frame_index != self.current_frame_index:
            self.reset()
            raise ValueError(
                f"Frame type or frame_index mismatch during reassembly: "
                f"({packet.frame_type}, {packet.frame_index}) vs ({self.current_type}, {self.current_frame_index})"
            )

        if len(self.buffer) + len(packet.payload) > self.max_payload_bytes:
            self.reset()
            raise ValueError("Payload size exceeds maximum allowed reassembly buffer")

        self.buffer.extend(packet.payload)
        self.last_seq_num = packet.seq_num
        self.expected_chunk += 1

        if is_last or (self.total_chunks > 0 and self.expected_chunk >= self.total_chunks):
            result_bytes = bytes(self.buffer)
            result_type = self.current_type
            self.reset()
            return True, result_bytes, result_type

        return False, None, None
