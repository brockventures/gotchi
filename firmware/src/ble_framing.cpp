// ============================================================================
// GOTCHI BLE 5.0 Packet Framing Protocol (T4.1 / F18) Implementation
// ============================================================================

#include "ble_framing.h"
#include <string.h>
#include <stdlib.h>

namespace gotchi_ble {

// CRC16-CCITT (Polynomial 0x1021, init 0xFFFF)
uint16_t calcCrc16(const uint8_t* data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < length; ++i) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (int bit = 0; bit < 8; ++bit) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

// CRC32 (Standard IEEE 802.3, Polynomial 0xEDB88320)
uint32_t calcCrc32(const uint8_t* data, size_t length) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < length; ++i) {
        uint8_t byte = data[i];
        crc ^= byte;
        for (int bit = 0; bit < 8; ++bit) {
            uint32_t mask = -(crc & 1);
            crc = (crc >> 1) ^ (0xEDB88320 & mask);
        }
    }
    return ~crc;
}

size_t encodePacket(
    FrameType type,
    uint16_t seq_num,
    uint16_t chunk_idx,
    uint16_t total_chunks,
    FrameFlags flags,
    const uint8_t* payload,
    size_t payload_len,
    uint8_t* out_buf,
    size_t out_cap
) {
    size_t total_needed = BLE_HEADER_SIZE + payload_len + BLE_TRAILER_SIZE;
    if (!out_buf || out_cap < total_needed) {
        return 0;
    }

    PacketHeader hdr;
    hdr.magic = BLE_MAGIC;
    hdr.frame_type = static_cast<uint8_t>(type);
    hdr.flags = static_cast<uint8_t>(flags);
    hdr.seq_num = seq_num;
    hdr.chunk_idx = chunk_idx;
    hdr.total_chunks = total_chunks;
    hdr.payload_len = static_cast<uint16_t>(payload_len);
    // Header CRC16 covers first 12 bytes (excluding header_crc16 field itself)
    hdr.header_crc16 = calcCrc16(reinterpret_cast<const uint8_t*>(&hdr), 12);

    memcpy(out_buf, &hdr, BLE_HEADER_SIZE);

    if (payload && payload_len > 0) {
        memcpy(out_buf + BLE_HEADER_SIZE, payload, payload_len);
    }

    uint32_t crc32 = (payload && payload_len > 0) ? calcCrc32(payload, payload_len) : 0;
    uint8_t* trailer = out_buf + BLE_HEADER_SIZE + payload_len;
    trailer[0] = static_cast<uint8_t>(crc32 & 0xFF);
    trailer[1] = static_cast<uint8_t>((crc32 >> 8) & 0xFF);
    trailer[2] = static_cast<uint8_t>((crc32 >> 16) & 0xFF);
    trailer[3] = static_cast<uint8_t>((crc32 >> 24) & 0xFF);

    return total_needed;
}

bool decodePacket(
    const uint8_t* in_buf,
    size_t in_len,
    Packet& out_packet
) {
    if (!in_buf || in_len < (BLE_HEADER_SIZE + BLE_TRAILER_SIZE)) {
        return false;
    }

    PacketHeader hdr;
    memcpy(&hdr, in_buf, BLE_HEADER_SIZE);

    if (hdr.magic != BLE_MAGIC) {
        return false;
    }

    uint16_t computed_crc16 = calcCrc16(in_buf, 12);
    if (computed_crc16 != hdr.header_crc16) {
        return false;
    }

    size_t expected_total = BLE_HEADER_SIZE + hdr.payload_len + BLE_TRAILER_SIZE;
    if (in_len < expected_total) {
        return false;
    }

    const uint8_t* payload = in_buf + BLE_HEADER_SIZE;
    const uint8_t* trailer = payload + hdr.payload_len;

    uint32_t payload_crc32 = static_cast<uint32_t>(trailer[0]) |
                             (static_cast<uint32_t>(trailer[1]) << 8) |
                             (static_cast<uint32_t>(trailer[2]) << 16) |
                             (static_cast<uint32_t>(trailer[3]) << 24);

    uint32_t computed_crc32 = (hdr.payload_len > 0) ? calcCrc32(payload, hdr.payload_len) : 0;
    if (computed_crc32 != payload_crc32) {
        return false;
    }

    out_packet.header = hdr;
    out_packet.payload = (hdr.payload_len > 0) ? payload : nullptr;
    out_packet.payload_crc32 = payload_crc32;
    return true;
}

PacketReassembler::PacketReassembler(size_t max_payload_size)
    : max_size_(max_payload_size) {
    buffer_ = static_cast<uint8_t*>(malloc(max_size_));
}

PacketReassembler::~PacketReassembler() {
    if (buffer_) {
        free(buffer_);
        buffer_ = nullptr;
    }
}

void PacketReassembler::reset() {
    current_len_ = 0;
    expected_chunk_ = 0;
    total_chunks_ = 0;
    in_progress_ = false;
}

bool PacketReassembler::pushPacket(const Packet& packet, bool& is_complete) {
    is_complete = false;
    if (!buffer_) return false;

    const PacketHeader& hdr = packet.header;
    bool is_first = (hdr.flags & static_cast<uint8_t>(FrameFlags::FIRST_CHUNK)) || (hdr.chunk_idx == 0);
    bool is_last = (hdr.flags & static_cast<uint8_t>(FrameFlags::LAST_CHUNK)) || (hdr.chunk_idx + 1 == hdr.total_chunks);

    if (is_first) {
        reset();
        current_type_ = static_cast<FrameType>(hdr.frame_type);
        total_chunks_ = hdr.total_chunks;
        expected_chunk_ = 0;
        in_progress_ = true;
    } else if (!in_progress_) {
        // Received mid-frame packet without first chunk
        return false;
    }

    // Verify chunk sequence continuity
    if (hdr.chunk_idx != expected_chunk_) {
        reset();
        return false;
    }

    // Type mismatch during reassembly
    if (static_cast<FrameType>(hdr.frame_type) != current_type_) {
        reset();
        return false;
    }

    // Check capacity
    if (current_len_ + hdr.payload_len > max_size_) {
        reset();
        return false;
    }

    if (hdr.payload_len > 0 && packet.payload) {
        memcpy(buffer_ + current_len_, packet.payload, hdr.payload_len);
        current_len_ += hdr.payload_len;
    }

    last_seq_num_ = hdr.seq_num;
    expected_chunk_++;

    if (is_last || (total_chunks_ > 0 && expected_chunk_ >= total_chunks_)) {
        is_complete = true;
        in_progress_ = false;
    }

    return true;
}

} // namespace gotchi_ble
