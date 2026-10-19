#pragma once
// ============================================================================
// GOTCHI BLE 5.0 Packet Framing Protocol (T4.1 / F18)
//   - High-throughput binary framing over BLE 5.0 2M PHY (GATT / L2CAP CoC).
//   - Frame types:
//       AUDIO_CHUNK (0x01): 16 kHz 16-bit mono PCM chunks.
//       IMAGE_FRAME (0x02): JPEG snapshot chunks (index, offset, total_bytes).
//       TURN_COMMIT (0x03): Marks end of user input / interaction dispatch.
//       SSE_EVENT   (0x04): Return events from gateway (state, audio, reply).
//       ACK         (0x05): Acknowledgment of packet / sequence receipt.
//       CANCEL      (0x06): Interaction abort / cancellation.
//   - Sequence numbers & chunk offsets for reliable reassembly.
//   - CRC16-CCITT header check and CRC32 payload check for link integrity.
// ============================================================================

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

namespace gotchi_ble {

constexpr uint16_t BLE_MAGIC = 0x4742; // "GB" (Gotchi BLE)
constexpr size_t BLE_HEADER_SIZE = 14;
constexpr size_t BLE_TRAILER_SIZE = 4; // CRC32 (4 bytes)
constexpr size_t BLE_MAX_PAYLOAD = 512 - BLE_HEADER_SIZE - BLE_TRAILER_SIZE; // 494 bytes for 512 MTU
constexpr size_t BLE_L2CAP_MAX_PAYLOAD = 2048; // Supported for L2CAP CoC

enum class FrameType : uint8_t {
    AUDIO_CHUNK = 0x01,
    IMAGE_FRAME = 0x02,
    TURN_COMMIT = 0x03,
    SSE_EVENT   = 0x04,
    ACK         = 0x05,
    CANCEL      = 0x06,
};

enum class FrameFlags : uint8_t {
    NONE        = 0x00,
    FIRST_CHUNK = 0x01,
    LAST_CHUNK  = 0x02,
    SINGLE_CHUNK = 0x03, // FIRST | LAST
    REQUIRES_ACK = 0x04,
};

inline FrameFlags operator|(FrameFlags a, FrameFlags b) {
    return static_cast<FrameFlags>(static_cast<uint8_t>(a) | static_cast<uint8_t>(b));
}
inline bool operator&(FrameFlags a, FrameFlags b) {
    return (static_cast<uint8_t>(a) & static_cast<uint8_t>(b)) != 0;
}

#pragma pack(push, 1)
struct PacketHeader {
    uint16_t magic;         // 0x4742 (Little-Endian)
    uint8_t  frame_type;    // FrameType
    uint8_t  flags;         // FrameFlags
    uint16_t seq_num;       // Monotonically increasing sequence number
    uint16_t chunk_idx;     // Chunk index within this frame/turn
    uint16_t total_chunks;  // Total chunks for this frame (1 if unknown/single)
    uint16_t payload_len;   // Payload length in bytes (excluding header & trailer)
    uint16_t header_crc16;  // CRC16-CCITT of preceding 12 bytes of header
};
#pragma pack(pop)

static_assert(sizeof(PacketHeader) == BLE_HEADER_SIZE, "PacketHeader must be exactly 14 bytes");

// CRC calculation helpers
uint16_t calcCrc16(const uint8_t* data, size_t length);
uint32_t calcCrc32(const uint8_t* data, size_t length);

struct Packet {
    PacketHeader header;
    const uint8_t* payload = nullptr;
    uint32_t payload_crc32 = 0;
};

// Encodes a packet into a preallocated buffer.
// Buffer must have at least BLE_HEADER_SIZE + payload_len + BLE_TRAILER_SIZE bytes.
// Returns total encoded bytes, or 0 on failure.
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
);

// Decodes and validates a raw packet from a buffer.
// Validates magic, header CRC16, length bounds, and payload CRC32.
// Returns true on success.
bool decodePacket(
    const uint8_t* in_buf,
    size_t in_len,
    Packet& out_packet
);

// Sequence tracker and defragmenter for incoming multi-chunk payloads
class PacketReassembler {
public:
    explicit PacketReassembler(size_t max_payload_size = 128 * 1024);
    ~PacketReassembler();

    void reset();

    // Ingests a decoded packet. Returns true if packet is accepted.
    // If this packet completes a fragmented turn/frame, `is_complete` is set to true.
    bool pushPacket(const Packet& packet, bool& is_complete);

    const uint8_t* getPayload() const { return buffer_; }
    size_t getPayloadLength() const { return current_len_; }
    FrameType getFrameType() const { return current_type_; }
    uint16_t getLastSeqNum() const { return last_seq_num_; }

private:
    size_t max_size_;
    uint8_t* buffer_ = nullptr;
    size_t current_len_ = 0;
    FrameType current_type_ = FrameType::AUDIO_CHUNK;
    uint16_t expected_chunk_ = 0;
    uint16_t total_chunks_ = 0;
    uint16_t last_seq_num_ = 0;
    bool in_progress_ = false;
};

} // namespace gotchi_ble
