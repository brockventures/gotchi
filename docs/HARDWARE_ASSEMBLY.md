# GOTCHI / SPRITE — Meatspace Hardware Assembly & Pinout Guide

This document contains the complete physical wiring instructions, GPIO pin multiplexing map, and bench bring-up checklist for assembling a V1 GOTCHI unit.

---

## 1. Master GPIO Pinout & Bus Allocation Map

The **XIAO ESP32S3 Sense** uses internal GPIOs (`GPIO10–18`, `38–42`, `47–48`) for its B2B camera and PDM microphone daughterboard, leaving **11 perimeter pins (`D0–D10`)** exposed on the main headers.

When plugged into the **Waveshare 1.54" E-Paper Module V2 (8-pin PH2.0 harness)**, 6 pins are routed to the 24-pin e-paper FPC connector, leaving **5 perimeter pins (`D2`, `D4`, `D6`, `D7`, `D9`)** free for audio, buttons, and V2 expansion.

### Complete Pin Allocation Table

| XIAO Pin | ESP32-S3 GPIO | RTC / Deep-Sleep Wake? | V1 Assigned Function | Hardware Connection |
| :--- | :--- | :--- | :--- | :--- |
| **`D0`** | `GPIO 1` | Yes (`RTC_GPIO1`) | **ePaper `RST`** (Reset) | Hardwired on Seeed ePaper Breakout |
| **`D1`** | `GPIO 2` | Yes (`RTC_GPIO2`) | **ePaper `CS`** (SPI Chip Select) | Hardwired on Seeed ePaper Breakout |
| **`D2`** | `GPIO 3` | **Yes (`RTC_GPIO3`)** | **BTN_TOP (Push-to-Talk & Wake)** | Hand-wired momentary switch to `GND` (`INPUT_PULLUP`) |
| **`D3`** | `GPIO 4` | Yes (`RTC_GPIO4`) | **ePaper `DC`** (Data/Command) | Hardwired on Seeed ePaper Breakout |
| **`D4`** | `GPIO 5` | **Yes (`RTC_GPIO5`)** | **BTN_BOT (Secondary / Mode / Snap)** | Hand-wired momentary switch to `GND` (`INPUT_PULLUP`); reclaimable for V2 wake hardware |
| **`D5`** | `GPIO 6` | Yes (`RTC_GPIO6`) | **ePaper `BUSY`** *(+ V2 `I2C_SCL`)* | Hardwired on Seeed ePaper Breakout ([Seeed Wiki](https://wiki.seeedstudio.com/epaper_breakout-board/)) |
| **`D6`** | `GPIO 43` | No | **I2S `LRCLK`** (Audio Word Select) | Wire to `MAX98357A` **`LRC`** pin *(UART0 TX at reset)* |
| **`D7`** | `GPIO 44` | No | **I2S `BCLK`** (Audio Bit Clock) | Wire to `MAX98357A` **`BCLK`** pin *(UART0 RX — silent at reset)* |
| **`D8`** | `GPIO 7` | No | **ePaper `SCK`** (SPI Clock) | Hardwired on Seeed ePaper Breakout |
| **`D9`** | `GPIO 8` | No | **I2S `DIN`** (Audio Data Out) | Wire to `MAX98357A` **`DIN`** pin *(MISO is unused by ePaper)* |
| **`D10`** | `GPIO 9` | No | **ePaper `MOSI`** (SPI Data Out) | Hardwired on Seeed ePaper Breakout |
| **`GPIO 0`** | `GPIO 0` | Yes (`RTC_GPIO0`) | **Reserved (`BOOT` Strapping Pad)** | Leave unattached in V1 so holding `BTN_BOT` at power-on never traps the MCU in ROM download mode |
| *Internal* | `GPIO 41` | — | **PDM Mic `CLK`** | Internal via Sense B2B Header |
| *Internal* | `GPIO 42` | — | **PDM Mic `DATA`** | Internal via Sense B2B Header |
| *Internal* | `GPIO 10–18, 38–40, 47–48` | — | **`OV5640` DVP Camera Bus** | Internal via Sense B2B Header |

> **Strapping & Boot-Glitch Protections (Amos + Zero Audit):**
> 1. **`BTN_BOT` Landed on `D4` (`GPIO 5`) Instead of `GPIO 0`:** `GPIO 0` is the ESP32-S3 ROM bootloader strapping pin. Landing `BTN_BOT` on `D4` (`GPIO 5` / `RTC_GPIO5`) eliminates the risk of entering USB download mode if the button is pressed in a pocket while flipping the power switch, and avoids micro-soldering to the tiny surface-mount `BOOT` pad. (If V2 adds an external I2C/wake module later, both buttons can multiplex onto a single ADC resistor ladder on `D2`).
> 2. **Pop-Free Boot on `MAX98357A` (`BCLK` on `D7` / `GPIO 44`):** `D6` (`GPIO 43`) is the ESP32-S3's default `UART0_TX`, which emits brief ROM boot messages at reset, whereas `D7` (`GPIO 44` / `UART0_RX`) is completely silent at boot. Routing **`BCLK` to `D7` (`GPIO 44`)** and **`LRCLK` to `D6` (`GPIO 43`)** ensures the `MAX98357A` sees zero valid bit-clock edges during ROM boot and stays muted until the I2S driver starts. Additionally, pull `MAX98357A SD` to `GND` via a **100 kΩ pull-down resistor** if wiring `SD` to a control pin, or rely on the clock-loss auto-shutdown with `BCLK` on silent `GPIO 44`.
> 3. **`BTN_TOP` on `D2` (`GPIO 3` Strapping Note):** `GPIO 3` is an optional JTAG-source strapping pin (only evaluated when `EFUSE_STRAP_JTAG_SEL` is burned, which is disabled by default from the factory). Leave `EFUSE_STRAP_JTAG_SEL` unburned (`0`) so holding PTT at power-on has zero effect on USB serial/JTAG.

---

## 2. Step-by-Step Meatspace Assembly Instructions

### Step 1: Camera Swap (`OV2640` -> `OV5640` Autofocus)
1. **Unplug the Sense Expansion Board** from the main XIAO ESP32-S3 before touching the camera ribbon.
2. Gently flip up the black locking bail on the 24-pin miniature camera FPC socket on the Sense expansion board.
3. Slide out the stock fixed-focus `OV2640` camera and insert the **`OV5640` 5MP Autofocus Camera**, ensuring the contacts face the PCB.
4. Press the locking bail flat and stick the included **aluminum/copper mini-heatsink** onto the flat metal backing of the camera module.

### Step 2: Battery Pads & Hardware Power Switch (Bottom of XIAO)
> **SAFETY WARNING:** Never connect or solder the LiPo battery while USB-C is plugged in. Insulate all exposed solder joints with Kapton tape.

1. Flip the main **XIAO ESP32-S3** board over to locate the two rectangular solder pads labeled **`BAT+`** and **`BAT-`** on the bottom surface.
2. Tin both `BAT+` and `BAT-` pads with a small bead of solder.
3. Solder the **black (`-`) lead** of the `803040` LiPo battery directly to the **`BAT-`** pad.
4. Solder the **red (`+`) lead** of the LiPo battery to the **center pin (common)** of the **SPDT Mini Slide Switch**.
5. Solder a short 30 AWG red wire from **one outer pin** of the slide switch to the XIAO **`BAT+`** pad. (Sliding the switch toward that outer pin turns the unit ON and enables USB-C charging; sliding it away completely isolates the battery).
6. Apply a strip of **Kapton tape** over the bottom of the XIAO board so the battery pads cannot short against the Waveshare 1.54" E-Paper Module V2 (8-pin PH2.0 harness) underneath.

### Step 3: Stacking XIAO + Sense Board + Seeed ePaper Breakout
1. Solder the two 7-pin male header strips onto the main XIAO ESP32-S3 (pins pointing **down** into the Seeed ePaper Breakout socket).
2. Snap the **Sense Camera/Mic expansion board** firmly onto the top B2B connector of the XIAO.
3. Snap the included **U.FL Wi-Fi/BLE flex antenna** onto the coaxial receptacle on the XIAO and route the adhesive antenna patch along the inner wall of the 3D-printed shell (keep it away from the metal speaker magnet).
4. Plug the XIAO assembly into the female headers on the **Waveshare 1.54" E-Paper Module V2 (8-pin PH2.0 harness)**, matching the USB-C port orientation marked on the silkscreen.
5. Unlock the 24-pin FPC connector on the Seeed ePaper Breakout, slide in the **1.54" 200x200 E-Paper ribbon cable**, and lock the latch.

### Step 4: Wiring the `MAX98357A` I2S Audio Amplifier
Use the 8-pin auxiliary header (or tap the XIAO header pins) to wire the **`MAX98357A`** breakout with 30 AWG silicone wire:
- **`MAX98357A VIN`** -> XIAO **`5V`** (or **`3V3`** for lower peak current on battery)
- **`MAX98357A GND`** -> XIAO **`GND`**
- **`MAX98357A BCLK`** -> XIAO **`D7` (`GPIO 44`)** *(Silent `UART0_RX` at boot — prevents ROM serial boot pop)*
- **`MAX98357A LRC`** -> XIAO **`D6` (`GPIO 43`)**
- **`MAX98357A DIN`** -> XIAO **`D9` (`GPIO 8`)**
- **`MAX98357A SD` (Shutdown)** -> Leave floating (internal pull-up keeps amp enabled in mono `(L+R)/2` mode; automatically enters `<1 µA` hardware shutdown whenever the ESP32-S3 stops the I2S clock).
- Solder the **1W 8Ω Micro-Speaker** leads to the `Speaker +` and `Speaker -` pads on the `MAX98357A`.

### Step 5: Wiring the Tactile Push Buttons
1. **Top Button (`BTN_TOP` — Push-to-Talk & Deep-Sleep Wake):**
   - Wire Pin 1 of the tactile switch to XIAO **`D2` (`GPIO 3` / `RTC_GPIO3`)**.
   - Wire Pin 2 of the tactile switch to **`GND`**.
2. **Bottom Button (`BTN_BOT` — Mode / Camera Snap / Cancel):**
   - Wire Pin 1 of the tactile switch directly to XIAO **`D4` (`GPIO 5` / `RTC_GPIO5`)**. *(Do not use `GPIO 0`, so holding the button during power-up cannot trigger ROM download mode).*
   - Wire Pin 2 of the tactile switch to **`GND`**.

---

## 3. First-Power & Smoke-Test Checklist

1. **Continuity & Short Check:** With the power switch **OFF** and USB-C unplugged, use a multimeter to verify there is no short between `3V3` and `GND` or `5V` and `GND`.
2. **USB-C Bring-Up:** Plug a USB-C data cable into your workstation, flip the slide switch **ON**, and verify `/dev/ttyACM0` (Linux) or `/dev/cu.usbmodem*` (macOS) enumerates.
3. **Automated Hardware Self-Test:** Once V1 firmware is flashed, send `{"cmd": "self_test"}` over USB serial (`115200` baud) and confirm all four peripherals pass:
   - `speaker`: Plays a 440 Hz chime on the `MAX98357A`.
   - `mic`: Samples non-zero RMS audio energy on the PDM mic (`GPIO41`/`42`).
   - `camera`: Initializes the `OV5640` at I2C address `0x3C`, triggers single-shot autofocus (`0x3022 = 0x08`), and returns a valid JPEG frame size/CRC.
   - `display`: Renders the 200x200 verification sprite and QR code on the e-paper panel.
