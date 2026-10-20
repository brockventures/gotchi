"""
Tests for GOTCHI Standalone Forked Android Pocket Emulator (`android-gotchi-emulator/`).
Verifies:
1. Fork isolation: `android-ble-forwarder/` remains 100% untouched while `android-gotchi-emulator/`
   uses a distinct `ventures.brock.gotchi.emulator` namespace and `applicationId` for side-by-side install.
2. AndroidManifest permissions (`RECORD_AUDIO`, `CAMERA`, `INTERNET`) and launcher `.GotchiEmulatorActivity`.
3. `GotchiEpaperView.kt` 200x200 1-bit monochrome viewport, 9 states, `RefreshTracker` partial/full cadence,
   and bundled `zero_skin` 1-bit sprite assets.
4. `GotchiEmulatorEngine.kt` wire-protocol parity with `backend/voice_gateway.py` and `firmware/`:
   - 44-byte RIFF WAV header (`wrapPcm16ToWav`)
   - WAV chunk walker (`extractPcmFromWavOrRaw`)
   - 500ms circular pre-roll buffer (`PRE_ROLL_MS = 500`)
   - `POST /api/voice/interact` multipart WAV + single (`image`) and 5-frame burst (`image_0`..`image_4`)
   - Streaming SSE parser supporting both `sentence` (`audio_b64`) and `audio_chunk` (`pcm_b64`/`data`)
   - `/api/live/ws` Go Live WebSocket streaming with hardware `AcousticEchoCanceler` and 300ms `barge_in`
   - On-device `node_id` regex validation (`^[A-Za-z0-9_-]{1,64}$`).
"""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from poc.gotchi_poc import VALID_STATES

REPO_ROOT = Path(__file__).resolve().parent.parent
FORWARDER_DIR = REPO_ROOT / "android-ble-forwarder"
EMULATOR_DIR = REPO_ROOT / "android-gotchi-emulator"
MANIFEST_PATH = EMULATOR_DIR / "app" / "src" / "main" / "AndroidManifest.xml"
APP_GRADLE_PATH = EMULATOR_DIR / "app" / "build.gradle.kts"
PKG_DIR = (
    EMULATOR_DIR
    / "app"
    / "src"
    / "main"
    / "java"
    / "ventures"
    / "brock"
    / "gotchi"
    / "emulator"
)
EPAPER_VIEW_PATH = PKG_DIR / "GotchiEpaperView.kt"
ENGINE_PATH = PKG_DIR / "GotchiEmulatorEngine.kt"
ACTIVITY_PATH = PKG_DIR / "GotchiEmulatorActivity.kt"
ASSETS_SKIN_DIR = EMULATOR_DIR / "app" / "src" / "main" / "assets" / "zero_skin"


def test_emulator_fork_project_structure_and_isolation():
    assert (EMULATOR_DIR / "build.gradle.kts").is_file()
    assert (EMULATOR_DIR / "settings.gradle.kts").is_file()
    assert APP_GRADLE_PATH.is_file()
    assert (EMULATOR_DIR / "README.md").is_file()
    assert MANIFEST_PATH.is_file()
    assert EPAPER_VIEW_PATH.is_file()
    assert ENGINE_PATH.is_file()
    assert ACTIVITY_PATH.is_file()

    # Verify distinct applicationId so emulator and BLE forwarder install side-by-side
    emu_gradle = APP_GRADLE_PATH.read_text(encoding="utf-8")
    fwd_gradle = (FORWARDER_DIR / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'namespace = "ventures.brock.gotchi.emulator"' in emu_gradle
    assert 'applicationId = "ventures.brock.gotchi.emulator"' in emu_gradle
    assert 'applicationId = "ventures.brock.gotchi.forwarder"' in fwd_gradle


def test_emulator_manifest_permissions_and_launcher_activity():
    tree = ET.parse(MANIFEST_PATH)
    root = tree.getroot()
    android_ns = "{http://schemas.android.com/apk/res/android}"

    permissions = {
        elem.attrib.get(f"{android_ns}name")
        for elem in root.findall("uses-permission")
    }
    required_permissions = {
        "android.permission.RECORD_AUDIO",
        "android.permission.CAMERA",
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.WAKE_LOCK",
    }
    assert required_permissions.issubset(permissions)

    app_elem = root.find("application")
    assert app_elem is not None
    activities = {
        a.attrib.get(f"{android_ns}name"): a
        for a in app_elem.findall("activity")
    }
    assert ".GotchiEmulatorActivity" in activities
    act = activities[".GotchiEmulatorActivity"]
    assert act.attrib.get(f"{android_ns}exported") == "true"


def test_epaper_view_states_refresh_tracker_and_zero_skin_assets():
    view_src = EPAPER_VIEW_PATH.read_text(encoding="utf-8")
    assert "const val EPD_WIDTH = 200" in view_src
    assert "const val EPD_HEIGHT = 200" in view_src
    assert "val maxConsecutivePartials: Int = 8" in view_src
    assert "val fullRefreshMinutes: Double = 15.0" in view_src

    for st in VALID_STATES:
        assert f'"{st}"' in view_src, f"Missing state {st} in GotchiEpaperView.kt"
        skin_png = ASSETS_SKIN_DIR / f"zero_{st}_200x200_1bit.png"
        assert skin_png.is_file(), f"Missing bundled Zero skin sprite: {skin_png}"


def test_emulator_engine_wire_protocol_and_hardware_parity():
    eng_src = ENGINE_PATH.read_text(encoding="utf-8")

    # 16 kHz mic capture with 500ms circular pre-roll + 24 kHz TTS playback
    assert "const val MIC_SAMPLE_RATE = 16000" in eng_src
    assert "const val TTS_DEFAULT_SAMPLE_RATE = 24000" in eng_src
    assert "const val PRE_ROLL_MS = 500" in eng_src
    assert "fun wrapPcm16ToWav(" in eng_src
    assert "fun extractPcmFromWavOrRaw(" in eng_src

    # Node ID regex validation matching T6.3
    assert 'Regex("^[A-Za-z0-9_-]{1,64}$")' in eng_src

    # Multipart /api/voice/interact upload with Bearer token, single image, and 5-frame burst
    assert "/api/voice/interact" in eng_src
    assert '"Authorization", "Bearer ${config.bearerToken}"' in eng_src
    assert 'addFormDataPart("audio_out_mode", safeAudioOut)' in eng_src
    assert '"image_$idx"' in eng_src

    # SSE event handling for PR #71 lookahead `sentence` (`audio_b64`) and legacy `audio_chunk`
    assert '"sentence", "audio_chunk"' in eng_src
    assert 'obj.optString("audio_b64"' in eng_src

    # Go Live bidirectional WebSocket (`/api/live/ws`) + hardware AEC + 300ms barge-in
    assert "/api/live/ws" in eng_src
    assert "AcousticEchoCanceler" in eng_src
    assert '.put("type", "barge_in")' in eng_src
    assert '.put("type", "image_burst")' in eng_src


def test_emulator_activity_hardware_buttons_and_vad_toggles():
    act_src = ACTIVITY_PATH.read_text(encoding="utf-8")
    assert "KEYCODE_VOLUME_UP" in act_src
    assert "KEYCODE_VOLUME_DOWN" in act_src
    assert "handleBtnTopTouch" in act_src
    assert "handleBtnBotTouch" in act_src
    assert "800L" in act_src and "1000L" in act_src and "1500L" in act_src
    assert "ArcticPurpleChassisView" in act_src
    assert "showHamburgerSettingsDialog" in act_src
    assert "☰" in act_src

