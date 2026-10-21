#!/usr/bin/env python3
"""
GOTCHI BLE 5.0 Packet Framing & 4-Bit IMA ADPCM Codec (T4.1 / F18)
==================================================================
Satisfies:
- Binary packet framing over BLE 5.0 2M PHY (GATT / L2CAP CoC).
- 16-byte packed header with magic (0x4742), frame_type, flags, burst frame_index (0..4),
  reserved byte, seq_num, chunk_idx, total_chunks, payload_len, and CRC16-CCITT check (14 bytes).
- 4-byte CRC32 payload validation trailer (IEEE 802.3, polynomial 0xEDB88320).
- Fragmentation into MTU-bounded chunks and stateful reassembly enforcing both
  chunk_idx and seq_num continuity.
- 4-bit IMA ADPCM audio compression (4:1 ratio; 64 kbps @ 16 kHz uplink / 96 kbps @ 24 kHz downlink)
  with 12-byte `GAD1` container header (`magic="GAD1"`, `sample_rate`, `num_samples`) for Smart Pipe
  BLE relay transcoding between ESP32-S3 and `GotchiBleRelayService`.
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

ADPCM_MAGIC = b"GAD1"
ADPCM_HEADER_SIZE = 12  # <4sII: "GAD1", sample_rate (uint32), num_samples (uint32)

IMA_INDEX_TABLE: Tuple[int, ...] = (
    -1, -1, -1, -1, 2, 4, 6, 8,
    -1, -1, -1, -1, 2, 4, 6, 8,
)

IMA_STEP_TABLE: Tuple[int, ...] = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17,
    19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118,
    130, 143, 157, 173, 190, 209, 230, 253, 279, 307,
    337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
    876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
    2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
    5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899,
    15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
)


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
    ADPCM        = 0x08  # 4-bit IMA ADPCM compressed audio payload


def _encode_ima_sample(sample: int, predictor: int, step_index: int) -> Tuple[int, int, int]:
    step = IMA_STEP_TABLE[step_index]
    diff = sample - predictor
    nibble = 0
    if diff < 0:
        nibble = 8
        diff = -diff
    if diff >= step:
        nibble |= 4
        diff -= step
    if diff >= (step >> 1):
        nibble |= 2
        diff -= (step >> 1)
    if diff >= (step >> 2):
        nibble |= 1

    vpdiff = step >> 3
    if nibble & 4:
        vpdiff += step
    if nibble & 2:
        vpdiff += step >> 1
    if nibble & 1:
        vpdiff += step >> 2

    if nibble & 8:
        predictor -= vpdiff
    else:
        predictor += vpdiff

    if predictor > 32767:
        predictor = 32767
    elif predictor < -32768:
        predictor = -32768

    step_index += IMA_INDEX_TABLE[nibble]
    if step_index < 0:
        step_index = 0
    elif step_index > 88:
        step_index = 88

    return nibble & 0x0F, predictor, step_index


def _decode_ima_nibble(nibble: int, predictor: int, step_index: int) -> Tuple[int, int]:
    step = IMA_STEP_TABLE[step_index]
    vpdiff = step >> 3
    if nibble & 4:
        vpdiff += step
    if nibble & 2:
        vpdiff += step >> 1
    if nibble & 1:
        vpdiff += step >> 2

    if nibble & 8:
        predictor -= vpdiff
    else:
        predictor += vpdiff

    if predictor > 32767:
        predictor = 32767
    elif predictor < -32768:
        predictor = -32768

    step_index += IMA_INDEX_TABLE[nibble & 0x0F]
    if step_index < 0:
        step_index = 0
    elif step_index > 88:
        step_index = 88

    return predictor, step_index


def encode_ima_adpcm(pcm_bytes: bytes) -> bytes:
    """
    Compresses 16-bit signed little-endian mono PCM into 4-bit IMA ADPCM nibbles (4:1 ratio).
    Low nibble holds sample 2*i; high nibble holds sample 2*i + 1.
    """
    num_samples = len(pcm_bytes) // 2
    if num_samples <= 0:
        return b""
    samples = struct.unpack(f"<{num_samples}h", pcm_bytes[: num_samples * 2])
    out = bytearray((num_samples + 1) // 2)
    predictor = 0
    step_index = 0

    for i in range(0, num_samples, 2):
        nib_lo, predictor, step_index = _encode_ima_sample(samples[i], predictor, step_index)
        if i + 1 < num_samples:
            nib_hi, predictor, step_index = _encode_ima_sample(samples[i + 1], predictor, step_index)
        else:
            nib_hi = 0
        out[i // 2] = (nib_lo & 0x0F) | ((nib_hi & 0x0F) << 4)

    return bytes(out)


def decode_ima_adpcm(adpcm_bytes: bytes, num_samples: Optional[int] = None) -> bytes:
    """
    Decompresses 4-bit IMA ADPCM nibbles back into 16-bit signed little-endian mono PCM.
    """
    if not adpcm_bytes:
        return b""
    total_nibbles = len(adpcm_bytes) * 2
    target_samples = total_nibbles if num_samples is None else min(max(0, int(num_samples)), total_nibbles)
    if target_samples <= 0:
        return b""

    out_samples: List[int] = []
    predictor = 0
    step_index = 0

    for byte_val in adpcm_bytes:
        nib_lo = byte_val & 0x0F
        predictor, step_index = _decode_ima_nibble(nib_lo, predictor, step_index)
        out_samples.append(predictor)
        if len(out_samples) >= target_samples:
            break

        nib_hi = (byte_val >> 4) & 0x0F
        predictor, step_index = _decode_ima_nibble(nib_hi, predictor, step_index)
        out_samples.append(predictor)
        if len(out_samples) >= target_samples:
            break

    return struct.pack(f"<{len(out_samples)}h", *out_samples)


def _extract_wav_pcm_and_rate(wav_or_pcm: bytes, default_sample_rate: int = 16000) -> Tuple[bytes, int]:
    if len(wav_or_pcm) >= 44 and wav_or_pcm[:4] == b"RIFF" and wav_or_pcm[8:12] == b"WAVE":
        sample_rate = default_sample_rate
        try:
            parsed_sr = struct.unpack_from("<I", wav_or_pcm, 24)[0]
            if 4000 <= parsed_sr <= 96000:
                sample_rate = parsed_sr
        except struct.error:
            pass
        offset = 12
        total_len = len(wav_or_pcm)
        while offset + 8 <= total_len:
            chunk_id = wav_or_pcm[offset : offset + 4]
            chunk_size = struct.unpack_from("<I", wav_or_pcm, offset + 4)[0]
            offset += 8
            if chunk_id == b"data":
                end = min(total_len, offset + chunk_size) if chunk_size < 0xFFFFFFFF else total_len
                return wav_or_pcm[offset:end], sample_rate
            offset += chunk_size + (chunk_size % 2)
        return wav_or_pcm[44:], sample_rate
    return wav_or_pcm, default_sample_rate


def _wrap_pcm_in_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    riff_size = 36 + len(pcm_bytes)
    byte_rate = sample_rate * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        byte_rate,
        2,
        16,
        b"data",
        len(pcm_bytes),
    )
    return header + pcm_bytes


def encode_wav_to_adpcm(wav_or_pcm: bytes, default_sample_rate: int = 16000) -> bytes:
    """
    Encodes a 16-bit mono WAV (or raw PCM buffer) into a `GAD1` 4-bit IMA ADPCM container:
    12-byte header (`GAD1`, `sample_rate: u32`, `num_samples: u32`) + packed ADPCM nibbles.
    """
    pcm_bytes, sample_rate = _extract_wav_pcm_and_rate(wav_or_pcm, default_sample_rate=default_sample_rate)
    num_samples = len(pcm_bytes) // 2
    adpcm_payload = encode_ima_adpcm(pcm_bytes)
    header = struct.pack("<4sII", ADPCM_MAGIC, int(sample_rate), int(num_samples))
    return header + adpcm_payload


def decode_adpcm_to_wav(adpcm_container: bytes, default_sample_rate: int = 16000) -> bytes:
    """
    Decodes a `GAD1` 4-bit IMA ADPCM container (or raw ADPCM stream) into a standard
    44-byte RIFF/WAVE 16-bit signed little-endian mono PCM file for `/api/voice/interact`.
    """
    if len(adpcm_container) >= ADPCM_HEADER_SIZE and adpcm_container[:4] == ADPCM_MAGIC:
        _, sample_rate, num_samples = struct.unpack("<4sII", adpcm_container[:ADPCM_HEADER_SIZE])
        if not (4000 <= sample_rate <= 96000):
            sample_rate = default_sample_rate
        raw_adpcm = adpcm_container[ADPCM_HEADER_SIZE:]
        pcm_bytes = decode_ima_adpcm(raw_adpcm, num_samples=num_samples)
    else:
        sample_rate = default_sample_rate
        pcm_bytes = decode_ima_adpcm(adpcm_container)
    return _wrap_pcm_in_wav(pcm_bytes, sample_rate=sample_rate)


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
    extra_flags: FrameFlags = FrameFlags.NONE,
) -> List[BlePacket]:
    """Splits a multi-byte payload into sequential MTU-bounded BlePacket instances."""
    if len(payload) == 0:
        flags = FrameFlags.SINGLE_CHUNK | extra_flags
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
        flags = FrameFlags.NONE | extra_flags
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
        self.current_flags: FrameFlags = FrameFlags.NONE
        self.current_frame_index: int = 0
        self.expected_chunk: int = 0
        self.total_chunks: int = 0
        self.last_seq_num: Optional[int] = None
        self.in_progress: bool = False

    def reset(self):
        self.buffer.clear()
        self.current_type = None
        self.current_flags = FrameFlags.NONE
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
            self.current_flags = packet.flags
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
        self.current_flags |= packet.flags
        self.last_seq_num = packet.seq_num
        self.expected_chunk += 1

        if is_last or (self.total_chunks > 0 and self.expected_chunk >= self.total_chunks):
            result_bytes = bytes(self.buffer)
            result_type = self.current_type
            self.reset()
            return True, result_bytes, result_type

        return False, None, None
