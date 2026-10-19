# GOTCHI / SPRITE — Meatspace Hardware Assembly, Pinout & Enclosure Envelope

This document contains the complete physical wiring instructions, GPIO pin multiplexing map, mechanical component dimensions for the multi-part 3D-printed enclosure, and bench bring-up checklist for assembling a V1 GOTCHI unit from the locked 7-item BOM ([`docs/BOM.md`](BOM.md)).

---

## 1. Master GPIO Pinout & Bus Allocation Map

The **XIAO ESP32S3 Sense** uses internal GPIOs (`GPIO10–18`, `38–42`, `47–48`) for its B2B camera and PDM microphone daughterboard, leaving **11 perimeter pins (`D0–D10`)** exposed on the main headers.

The **Waveshare 1.54" E-Paper Module V2 (`SKU 12955` / Amazon `B0728BJTZC`)** includes an **8-pin PH2.0 wire harness** (`VCC`, `GND`, `DIN`, `CLK`, `CS`, `DC`, `RST`, `BUSY`) that wires directly to 6 XIAO perimeter pins plus `3V3`/`GND` (replacing the discontinued Seeed ePaper Breakout), leaving **5 perimeter pins (`D2`, `D4`, `D6`, `D7`, `D9`)** free for I2S audio, tactile buttons, and V2 expansion.

### Complete Pin Allocation Table

| XIAO Pin | ESP32-S3 GPIO | RTC / Deep-Sleep Wake? | V1 Assigned Function | Hardware Connection (Direct Harness / Wire) |
| :--- | :--- | :--- | :--- | :--- |
| **`D0`** | `GPIO 1` | Yes (`RTC_GPIO1`) | **ePaper `RST`** (Reset) | Waveshare 8-pin PH2.0 Harness **`RST`** |
| **`D1`** | `GPIO 2` | Yes (`RTC_GPIO2`) | **ePaper `CS`** (SPI Chip Select) | Waveshare 8-pin PH2.0 Harness **`CS`** |
| **`D2`** | `GPIO 3` | **Yes (`RTC_GPIO3`)** | **BTN_TOP (Push-to-Talk & Wake)** | Momentary `6x6x5mm` switch to `GND` (`INPUT_PULLUP`) |
| **`D3`** | `GPIO 4` | Yes (`RTC_GPIO4`) | **ePaper `DC`** (Data/Command) | Waveshare 8-pin PH2.0 Harness **`DC`** |
| **`D4`** | `GPIO 5` | **Yes (`RTC_GPIO5`)** | **BTN_BOT (Secondary / Mode / Snap)** | Momentary `6x6x5mm` switch to `GND` (`INPUT_PULLUP`); reclaimable for V2 wake hardware |
| **`D5`** | `GPIO 6` | Yes (`RTC_GPIO6`) | **ePaper `BUSY`** *(+ V2 `I2C_SCL`)* | Waveshare 8-pin PH2.0 Harness **`BUSY`** |
| **`D6`** | `GPIO 43` | No | **I2S `LRCLK`** (Audio Word Select) | Wire to `MAX98357A` **`LRC`** pin *(UART0 TX at reset)* |
| **`D7`** | `GPIO 44` | No | **I2S `BCLK`** (Audio Bit Clock) | Wire to `MAX98357A` **`BCLK`** pin *(UART0 RX — silent at reset)* |
| **`D8`** | `GPIO 7` | No | **ePaper `SCK`** (SPI Clock) | Waveshare 8-pin PH2.0 Harness **`CLK`** |
| **`D9`** | `GPIO 8` | No | **I2S `DIN`** (Audio Data Out) | Wire to `MAX98357A` **`DIN`** pin *(MISO unused by ePaper)* |
| **`D10`** | `GPIO 9` | No | **ePaper `MOSI`** (SPI Data Out) | Waveshare 8-pin PH2.0 Harness **`DIN`** |
| **`3V3`** | — | — | **3.3V Regulated Rail** | Waveshare 8-pin PH2.0 Harness **`VCC`** (+ optional `MAX98357A VIN`) |
| **`5V`** | — | — | **5V / VBUS Rail** | Optional `MAX98357A VIN` |
| **`GND`** | — | — | **Common Ground** | Waveshare **`GND`**, `MAX98357A` **`GND`**, `BTN_TOP`, `BTN_BOT` |
| **`GPIO 0`** | `GPIO 0` | Yes (`RTC_GPIO0`) | **Reserved (`BOOT` Strapping Pad)** | Leave unattached in V1 so holding `BTN_BOT` at power-on never traps the MCU in ROM download mode |
| *Internal* | `GPIO 41` | — | **PDM Mic `CLK`** | Internal via Sense B2B Header |
| *Internal* | `GPIO 42` | — | **PDM Mic `DATA`** | Internal via Sense B2B Header |
| *Internal* | `GPIO 10–18, 38–40, 47–48` | — | **DVP Camera Bus (`OV2640`/`OV3660` or `OV5640`)** | Internal via Sense B2B Header |

> **Strapping & Boot-Glitch Protections (Amos + Zero Audit):**
> 1. **`BTN_BOT` Landed on `D4` (`GPIO 5`) Instead of `GPIO 0`:** `GPIO 0` is the ESP32-S3 ROM bootloader strapping pin. Landing `BTN_BOT` on `D4` (`GPIO 5` / `RTC_GPIO5`) eliminates the risk of entering USB download mode if the button is pressed in a pocket while flipping the power switch, and avoids micro-soldering to the tiny surface-mount `BOOT` pad.
> 2. **Pop-Free Boot on `MAX98357A` (`BCLK` on `D7` / `GPIO 44`):** `D6` (`GPIO 43`) is the ESP32-S3's default `UART0_TX`, which emits brief ROM boot messages at reset, whereas `D7` (`GPIO 44` / `UART0_RX`) is completely silent at boot. Routing **`BCLK` to `D7` (`GPIO 44`)** and **`LRCLK` to `D6` (`GPIO 43`)** ensures the `MAX98357A` sees zero valid bit-clock edges during ROM boot and stays muted until the I2S driver starts.
> 3. **`BTN_TOP` on `D2` (`GPIO 3` Strapping Note):** `GPIO 3` is an optional JTAG-source strapping pin (only evaluated when `EFUSE_STRAP_JTAG_SEL` is burned, which is disabled by default from the factory). Leave `EFUSE_STRAP_JTAG_SEL` unburned (`0`) so holding PTT at power-on has zero effect on USB serial/JTAG.

---

## 2. Step-by-Step Meatspace Assembly Instructions

### Step 1: Camera & Sense Expansion Board Check
1. **Stock V1 Baseline (No Swap Required):** The **XIAO ESP32S3 Sense** ships with its stock camera (`OV2640` / `OV3660`) pre-installed on the Sense expansion board alongside the digital PDM microphone. Stick the included mini heatsink onto the flat backing of the camera module and snap the Sense board onto the top B2B header of the XIAO.
2. **Optional `OV5640` 5MP Autofocus Upgrade (`$11.99`):** If installing the optional `OV5640` camera, unplug the Sense board from the XIAO first, flip up the black locking bail on the 24-pin FPC socket, swap in the `OV5640` ribbon (contacts facing the PCB), press the locking bail flat, and attach the heatsink.
3. Snap the included **U.FL Wi-Fi/BLE flex antenna** onto the coaxial receptacle on the XIAO and route the adhesive antenna patch along the inner plastic wall of the enclosure away from the speaker magnet.

### Step 2: Battery Pads & Hardware Power Switch (Bottom of XIAO)
> **SAFETY WARNING:** Never connect or solder the LiPo battery while USB-C is plugged in. Always verify wire polarity (`red = BAT+`, `black = BAT-`) before soldering, and insulate all exposed joints with Kapton tape.

1. Cut the factory 2-pin JST plug off the **`803040` 3.7V 1000mAh LiPo battery (`B0FRFY7KLH`)** one lead at a time (never cut both wires simultaneously with metal cutters) and strip `~3 mm` of insulation.
2. Flip the main **XIAO ESP32-S3** board over to locate the two rectangular solder pads labeled **`BAT+`** and **`BAT-`** on the bottom surface, and tin both pads.
3. Solder the **black (`-`) battery lead** directly to the XIAO **`BAT-`** pad.
4. Solder the **red (`+`) battery lead** to the **center pin (common)** of the **Mini SPDT 3-Pin Slide Switch (`B0FNK8B1YV`)**.
5. Solder a short 28–30 AWG red wire from **one outer pin** of the slide switch to the XIAO **`BAT+`** pad. (Sliding the switch toward that outer pin turns the unit ON and enables USB-C LiPo charging; sliding it away completely disconnects the battery).
6. Apply a strip of **Kapton tape** over the bottom of the XIAO board to insulate the solder pads.

### Step 3: Wiring the Waveshare 1.54" E-Paper Module V2 (`SKU 12955` / `B0728BJTZC`)
Plug the included **8-pin PH2.0 connector** into the back of the Waveshare 1.54" E-Paper Module V2 PCB and solder/connect the 8 leads directly to the XIAO ESP32S3:
- **`VCC`** -> XIAO **`3V3`**
- **`GND`** -> XIAO **`GND`**
- **`DIN` (MOSI)** -> XIAO **`D10` (`GPIO 9`)**
- **`CLK` (SCK)** -> XIAO **`D8` (`GPIO 7`)**
- **`CS`** -> XIAO **`D1` (`GPIO 2`)**
- **`DC`** -> XIAO **`D3` (`GPIO 4`)**
- **`RST`** -> XIAO **`D0` (`GPIO 1`)**
- **`BUSY`** -> XIAO **`D5` (`GPIO 6`)**

### Step 4: Wiring the `MAX98357A` I2S Audio Amplifier (`B0DPJRLMDJ`) & Speaker (`B0D7S8FFKY`)
Wire the **`MAX98357A`** breakout to the XIAO with 30 AWG silicone wire:
- **`MAX98357A VIN`** -> XIAO **`5V`** (or **`3V3`** for lower peak battery current)
- **`MAX98357A GND`** -> XIAO **`GND`**
- **`MAX98357A BCLK`** -> XIAO **`D7` (`GPIO 44`)** *(Silent `UART0_RX` at boot — prevents ROM serial boot pop)*
- **`MAX98357A LRC`** -> XIAO **`D6` (`GPIO 43`)**
- **`MAX98357A DIN`** -> XIAO **`D9` (`GPIO 8`)**
- **`MAX98357A SD` (Shutdown)** -> Leave floating (internal pull-up keeps amp enabled in mono `(L+R)/2` mode; automatically enters `<1 µA` hardware shutdown whenever the ESP32-S3 stops the I2S clock).
- Connect or solder the **1W 8Ω Mini Cavity Speaker (`B0D7S8FFKY`)** leads to the `+` and `-` audio output terminals on the `MAX98357A`.

### Step 5: Wiring the Tactile Push Buttons (`6x6x5mm`, `B07VSNN9S2`)
1. **Top Button (`BTN_TOP` — Push-to-Talk & Deep-Sleep Wake):**
   - Wire Pin 1 of the tactile switch to XIAO **`D2` (`GPIO 3` / `RTC_GPIO3`)**.
   - Wire Pin 2 of the tactile switch to **`GND`**.
2. **Bottom Button (`BTN_BOT` — Mode / Camera Snap / Cancel):**
   - Wire Pin 1 of the tactile switch directly to XIAO **`D4` (`GPIO 5` / `RTC_GPIO5`)**. *(Never wire to `GPIO 0`).*
   - Wire Pin 2 of the tactile switch to **`GND`**.

---

## 3. Mechanical Component Envelope (For Multi-Part Blender / CAD Case)

Reference dimensions for the locked 7-item V1 BOM (`cad/` multi-part openable shell):

| # | Component | Nominal Dimensions (`L x W x H`) | Enclosure Cutout & Mounting Notes |
| :--- | :--- | :--- | :--- |
| **1** | **XIAO ESP32S3 + Sense Stack** | `21.0 x 17.8 x ~15.0 mm` | `USB-C` receptacle (`9.0 x 3.4 mm` opening) on edge; camera lens window (`~8.5 x 8.5 mm`) + PDM mic pinhole (`Ø 1.5 mm`) on Sense board; `U.FL` flex antenna patch (`~42 x 12 mm`). |
| **2** | **Waveshare 1.54" E-Paper V2 (`SKU 12955`)** | **`48.0 x 33.0 x ~2.8 mm`** *(+ `~5.5 mm` rear PH2.0 header)* | Active viewing bezel opening: **`27.6 x 27.6 mm`** (`200x200` px). 4x **`M2` (`Ø 2.0 mm`)** corner mounting holes (`~43.0 x 28.0 mm` hole centers). |
| **3** | **MAX98357A I2S Amp (`B0DPJRLMDJ`)** | `~19.0 x 17.8 x 3.0 mm` | Internal tray or siderib slot; 2x `M2` mounting holes. |
| **4** | **1W 8Ω Cavity Speaker (`B0D7S8FFKY`)** | `~20.0 x 14.0 x 3.5 mm` *(allow `31 x 21 x 5 mm` bay)* | Enclosed resonant micro-speaker; place front sound grille slots facing outward. |
| **5** | **`803040` 1000mAh LiPo (`B0FRFY7KLH`)** | **`40.0 x 30.0 x 8.0 mm`** *(design bay **`42.0 x 32.0 x 9.0 mm`**)* | Flat rear compartment in the back shell half with `1.0 mm` swell clearance and wire exit channel. |
| **6** | **2x Tactile Buttons (`B07VSNN9S2`)** | `6.0 x 6.0 x 5.0 mm` (`3.5 mm` base + `1.5 mm` stem) | Side-edge cradle for `BTN_TOP` (PTT) and `BTN_BOT` (Mode/Snap) with captive button caps or compliant flex paddles. |
| **7** | **Mini SPDT Slide Switch (`B0FNK8B1YV`)** | `~8.5 x 3.5 x 4.0 mm` (`2.0 mm` slider travel) | Recessed perimeter slot (`~4.5 x 2.0 mm` window) so the power switch cannot flip accidentally in a pocket. |

---

## 4. First-Power & Smoke-Test Checklist

1. **Continuity & Short Check:** With the power switch **OFF** and USB-C unplugged, use a multimeter to verify there is no short between `3V3` and `GND` or `5V` and `GND`.
2. **USB-C Bring-Up:** Plug a USB-C data cable into your workstation, flip the slide switch **ON**, and verify `/dev/ttyACM0` (Linux) or `/dev/cu.usbmodem*` (macOS) enumerates.
3. **Automated Hardware Self-Test:** Once V1 firmware is flashed, send `{"cmd": "self_test"}` over USB serial (`115200` baud) and confirm all four peripherals pass:
   - `speaker`: Plays a 440 Hz chime on the `MAX98357A`.
   - `mic`: Samples non-zero RMS audio energy on the PDM mic (`GPIO41`/`42`).
   - `camera`: Initializes the stock `OV2640`/`OV3660` (or optional `OV5640` AF) camera on the DVP bus and returns a valid JPEG frame size/CRC.
   - `display`: Renders the 200x200 verification sprite and QR code on the Waveshare 1.54" V2 e-paper panel.
