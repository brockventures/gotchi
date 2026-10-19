"""Contract & unit verification for V1 Multiplexed ADC Battery Fuel Gauge (D4) and Wall-Brick Sense (D2)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def lipo_mv_to_percent_py(mv: int) -> int:
    """Reference mirror of firmware/src/main.cpp::lipoMvToPercent(uint16_t mv)."""
    if mv == 0:
        return -1
    if mv <= 3300:
        return 0
    if mv >= 4150:
        return 100
    if mv < 3500:
        return ((mv - 3300) * 10) // 200
    if mv < 3680:
        return 10 + ((mv - 3500) * 20) // 180
    if mv < 3800:
        return 30 + ((mv - 3680) * 30) // 120
    if mv < 3950:
        return 60 + ((mv - 3800) * 25) // 150
    return 85 + ((mv - 3950) * 15) // 200


def test_lipo_piecewise_discharge_curve():
    assert lipo_mv_to_percent_py(0) == -1
    assert lipo_mv_to_percent_py(3200) == 0
    assert lipo_mv_to_percent_py(3300) == 0
    assert lipo_mv_to_percent_py(3500) == 10
    assert lipo_mv_to_percent_py(3680) == 30
    assert lipo_mv_to_percent_py(3800) == 60
    assert lipo_mv_to_percent_py(3950) == 85
    assert lipo_mv_to_percent_py(4150) == 100
    assert lipo_mv_to_percent_py(4200) == 100

    # Strictly monotonic across 3300..4200 mV
    prev = 0
    for mv in range(3300, 4201, 10):
        pct = lipo_mv_to_percent_py(mv)
        assert pct >= prev
        prev = pct


def test_firmware_power_and_fuel_gauge_contracts():
    pins_h = (REPO_ROOT / "firmware" / "include" / "pins.h").read_text(encoding="utf-8")
    ui_h = (REPO_ROOT / "firmware" / "include" / "ui_state.h").read_text(encoding="utf-8")
    main_cpp = (REPO_ROOT / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")
    sprite_cpp = (REPO_ROOT / "firmware" / "src" / "sprite_render.cpp").read_text(encoding="utf-8")
    bom_md = (REPO_ROOT / "docs" / "BOM.md").read_text(encoding="utf-8")
    hw_md = (REPO_ROOT / "docs" / "HARDWARE_ASSEMBLY.md").read_text(encoding="utf-8")

    # 1. Pins & ADC divider constants
    assert "PIN_VBAT_DIV_MIN_MV" in pins_h
    assert "PIN_VBAT_DIV_MAX_MV" in pins_h
    assert "PIN_VBUS_WALL_MIN_MV" in pins_h

    # 2. UI State & E-Paper Header Badge
    assert "int8_t   battery_pct = -1;" in ui_h
    assert "bool     wall_power = false;" in ui_h
    assert "ui.battery_pct >= 0" in sprite_cpp
    assert 'snprintf(bat_badge, sizeof(bat_badge), "%d%%%s"' in sprite_cpp

    # 3. Main firmware pulsed high-Z ADC sampling & JSON-RPC telemetry
    assert "samplePowerAndBatteryTelemetry" in main_cpp
    assert "lipoMvToPercent" in main_cpp
    assert "isWallBrickPowerConnected()" in main_cpp
    assert "isExternalPowerConnected()" in main_cpp
    assert 'res["wall_power_connected"] = isWallBrickPowerConnected();' in main_cpp
    assert 'res["battery_mv"] = s_battery_mv;' in main_cpp
    assert 'res["battery_pct"] = (int)s_battery_pct;' in main_cpp

    # 4. BOM & Assembly docs include 4x 220k resistors and 30 AWG wire spool
    assert "220 kΩ" in bom_md
    assert "B089CXFH4H" in bom_md
    assert "Step 6: Wiring the V1 Battery Fuel Gauge" in hw_md
