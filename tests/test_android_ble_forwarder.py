"""
Tests for GOTCHI Headless Android BLE-to-Tailscale Forwarder (T4.2 / F18 / Issue #22).
Verifies project structure, AndroidManifest permissions/service declaration, and
cross-language wire-protocol parity between Kotlin BleFramingCodec, C++ ble_framing.h,
and Python backend/ble_framing.py.
"""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from backend.ble_framing import (
    BLE_DEFAULT_MTU,
    BLE_HEADER_SIZE,
    BLE_MAGIC,
    BLE_MAX_CHUNK_PAYLOAD,
    BLE_TRAILER_SIZE,
    FrameFlags,
    FrameType,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ANDROID_DIR = REPO_ROOT / "android-ble-forwarder"
MANIFEST_PATH = ANDROID_DIR / "app" / "src" / "main" / "AndroidManifest.xml"
CODEC_PATH = (
    ANDROID_DIR
    / "app"
    / "src"
    / "main"
    / "java"
    / "ventures"
    / "brock"
    / "gotchi"
    / "forwarder"
    / "BleFramingCodec.kt"
)
SERVICE_PATH = (
    ANDROID_DIR
    / "app"
    / "src"
    / "main"
    / "java"
    / "ventures"
    / "brock"
    / "gotchi"
    / "forwarder"
    / "GotchiBleRelayService.kt"
)
RECEIVER_PATH = (
    ANDROID_DIR
    / "app"
    / "src"
    / "main"
    / "java"
    / "ventures"
    / "brock"
    / "gotchi"
    / "forwarder"
    / "BootCompletedReceiver.kt"
)


def test_android_project_files_exist():
    assert (ANDROID_DIR / "build.gradle.kts").is_file()
    assert (ANDROID_DIR / "settings.gradle.kts").is_file()
    assert (ANDROID_DIR / "app" / "build.gradle.kts").is_file()
    assert (ANDROID_DIR / "README.md").is_file()
    assert MANIFEST_PATH.is_file()
    assert CODEC_PATH.is_file()
    assert SERVICE_PATH.is_file()
    assert RECEIVER_PATH.is_file()


def test_android_manifest_permissions_and_foreground_service():
    tree = ET.parse(MANIFEST_PATH)
    root = tree.getroot()
    android_ns = "{http://schemas.android.com/apk/res/android}"

    permissions = {
        elem.attrib.get(f"{android_ns}name")
        for elem in root.findall("uses-permission")
    }
    required_permissions = {
        "android.permission.BLUETOOTH_SCAN",
        "android.permission.BLUETOOTH_CONNECT",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
        "android.permission.INTERNET",
        "android.permission.RECEIVE_BOOT_COMPLETED",
    }
    assert required_permissions.issubset(permissions)

    app_elem = root.find("application")
    assert app_elem is not None

    services = {
        s.attrib.get(f"{android_ns}name"): s
        for s in app_elem.findall("service")
    }
    assert ".GotchiBleRelayService" in services
    relay_service = services[".GotchiBleRelayService"]
    assert relay_service.attrib.get(f"{android_ns}foregroundServiceType") == "connectedDevice"

    receivers = {
        r.attrib.get(f"{android_ns}name"): r
        for r in app_elem.findall("receiver")
    }
    assert ".BootCompletedReceiver" in receivers


def test_kotlin_ble_framing_codec_wire_parity():
    codec_src = CODEC_PATH.read_text(encoding="utf-8")

    magic_match = re.search(r"const val MAGIC:\s*Int\s*=\s*0x([0-9A-Fa-f]+)", codec_src)
    assert magic_match and int(magic_match.group(1), 16) == BLE_MAGIC

    header_match = re.search(r"const val HEADER_BYTES:\s*Int\s*=\s*(\d+)", codec_src)
    assert header_match and int(header_match.group(1)) == BLE_HEADER_SIZE

    trailer_match = re.search(r"const val TRAILER_BYTES:\s*Int\s*=\s*(\d+)", codec_src)
    assert trailer_match and int(trailer_match.group(1)) == BLE_TRAILER_SIZE

    mtu_match = re.search(r"const val DEFAULT_GATT_MTU:\s*Int\s*=\s*(\d+)", codec_src)
    assert mtu_match and int(mtu_match.group(1)) == BLE_DEFAULT_MTU

    payload_match = re.search(r"const val DEFAULT_MAX_PAYLOAD:\s*Int\s*=\s*(\d+)", codec_src)
    assert payload_match and int(payload_match.group(1)) == BLE_MAX_CHUNK_PAYLOAD

    for ft in FrameType:
        pattern = rf"{ft.name}\(0x{int(ft):02X}\)"
        assert re.search(pattern, codec_src), f"Missing or mismatched FrameType {ft.name} in Kotlin codec"

    for ff in FrameFlags:
        pattern = rf"FLAG_{ff.name}:\s*Int\s*=\s*0x{int(ff):02X}"
        assert re.search(pattern, codec_src), f"Missing or mismatched FrameFlags {ff.name} in Kotlin codec"

    # Verify CRC16 is computed over first 14 bytes of the 16-byte header
    assert "crc16Ccitt(prefixBytes, 0, 14)" in codec_src
    assert "crc16Ccitt(raw, 0, 14)" in codec_src
    # Verify cross-frame sequence continuity and interrupted multi-chunk detection
    assert "seq_num_discontinuity" in codec_src
    assert "interrupted_multi_chunk_frame" in codec_src


def test_gotchi_ble_relay_service_capabilities():
    service_src = SERVICE_PATH.read_text(encoding="utf-8")

    # BLE 5.0 2M PHY and 512 MTU negotiation
    assert "PHY_LE_2M_MASK" in service_src
    assert "requestMtu(BleFramingCodec.DEFAULT_GATT_MTU)" in service_src

    # GATT Service and Characteristic UUIDs
    assert "6E400001-B5A3-F393-E0A9-E50E24DCCA9E" in service_src
    assert "6E400002-B5A3-F393-E0A9-E50E24DCCA9E" in service_src
    assert "6E400003-B5A3-F393-E0A9-E50E24DCCA9E" in service_src

    # Tailscale HTTP multipart relay with Bearer token and audio_out_mode
    assert "/api/voice/interact" in service_src
    assert '"Authorization", "Bearer $bearerToken"' in service_src
    assert 'addFormDataPart("audio_out_mode", audioOutMode)' in service_src
    assert 'addFormDataPart(\n                        "image_$idx"' in service_src or '"image_$idx"' in service_src

    # Local phone/earbud playback when audio_out_mode == "ble_phone"
    assert 'audioOutMode == "ble_phone"' in service_src
    assert "playPcmOnPhoneSpeaker" in service_src

    # Smart Pipe offload capabilities:
    # 1. 4-bit IMA ADPCM uplink & downlink transcoding
    codec_src = CODEC_PATH.read_text(encoding="utf-8")
    assert "object ImaAdpcmCodec" in codec_src
    assert "decodeGad1OrAdpcmToWav" in codec_src
    assert "encodePcmToGad1" in codec_src
    assert "transcodeUplinkAudioIfNeeded" in service_src
    assert "transcodeDownlinkAudioEventToAdpcm" in service_src

    # 2. Dead-zone store-and-forward offline spooling + 4xx poison-pill eviction + SSE mid-stream guard
    assert "spoolTurnForOfflineReplay" in service_src
    assert "drainOfflineSpool" in service_src
    assert '"offline_queued"' in service_src
    assert "enum class PostOutcome" in service_src
    assert "PERMANENT_FAILURE" in service_src
    assert "responseStarted = true" in service_src
    assert "if (responseStarted)" in service_src
    assert "e is IllegalArgumentException" in service_src
    assert "catch (e: JSONException)" in service_src
    assert "encodePcmToGad1WithState" in codec_src
    assert "downlinkAdpcmPredictor" in service_src
    assert "downlinkAdpcmStepIndex" in service_src

    # 3. Passive coarse GPS location metadata tagging
    assert "readCoarseLocationMeta" in service_src
    assert 'addFormDataPart("lat"' in service_src
    assert 'addFormDataPart("lon"' in service_src
    assert 'addFormDataPart("location_accuracy_m"' in service_src
    assert 'addFormDataPart("offline_replay", "true")' in service_src

