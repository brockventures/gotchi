# GOTCHI / SPRITE — V1 Bill of Materials (BOM) & Live 1-Unit Shopping List

Verified live pricing & stock as of **2026-10-19** for a **single-unit prototype build** (each builder orders 1 cart for their own bench: **Ryan** and **Mike / Arbiter**).

### Key V1 Hardware Decisions Locked
1. **No Seeed ePaper Breakout Needed:** The discontinued Seeed ePaper Breakout (`p-5804`) is removed. The **Waveshare 1.54" E-Paper Module V2** (`SKU 12955` / Amazon `B0728BJTZC`) is a complete 8-pin SPI module (`48.0 x 33.0 mm`) with an onboard 3.3V/5V voltage translator, boost circuit, four M2 mounting holes, and an included 8-pin PH2.0 wire harness that wires directly to the XIAO ESP32S3 Sense (`D0/D1/D3/D5/D8/D10` + `3V3/GND`).
2. **Stock Camera Baseline ($0 Extra):** The **XIAO ESP32S3 Sense** includes a stock plug-in camera (`OV2640` / `OV3660` depending on batch) and digital PDM microphone in the box. Seeed's official `OV5640` autofocus camera (`$11.99`) is strictly optional (slotted for **V2.2**).
3. **V1 Battery Fuel Gauge (`%`) & Wall-Brick (`5V VBUS`) Detection via 3x `220 kΩ` Resistors:** Because the XIAO ESP32S3 does not route `VBUS` (`5V`) or `VBAT` internally to any GPIO, V1 uses a symmetric **`220 kΩ / 220 kΩ` voltage divider** on `D4` (`GPIO5` / `ADC1_CH4`, shared with `BTN_BOT`) for live LiPo state-of-charge (`0–100%`) and a **single `220 kΩ` series resistor** from `5V` (`VBUS`) to `D2` (`GPIO3` / `ADC1_CH2`, shared with `BTN_TOP`, sampled against internal `45 kΩ` `INPUT_PULLDOWN`) for dumb 5V USB-C wall-brick detection — requiring zero extra GPIOs and keeping `D2 >= 2.74 V` on battery.
4. **1-Unit Core Electronics Cart Totals (Before Shipping & Tax):**
   - **3-Vendor Lowest Item Price (Seeed + Waveshare + Amazon):** **$68.81** (`$13.99` Seeed XIAO + `$9.99` Waveshare panel + `$44.83` Amazon audio/power/controls/resistors)
   - **2-Vendor Fast Domestic Mix (Seeed + Amazon w/ Prime Panel):** **$76.81** (`$13.99` Seeed XIAO + `$62.82` Amazon cart including `$17.99` Waveshare V2 panel)
   - **All-Amazon 1-Cart Option:** **$86.81** (`$23.99` Amazon XIAO + `$62.82` Amazon cart)

---

## 1. Core Single-Unit Electronics Shopping List (8 Items)

| # | Component | Spec & Role | Live Price | Verified Store Links |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Seeed Studio XIAO ESP32S3 Sense** | ESP32-S3, 8MB PSRAM, 8MB Flash, stock camera + PDM mic (`MPN 113991115`) | **$13.99** (Seeed)<br>**$23.99** (Amazon) | [Seeed Studio ($13.99)](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html) · [Amazon `B0C69FFVHH` ($23.99)](https://www.amazon.com/dp/B0C69FFVHH) |
| **2** | **Waveshare 1.54" E-Paper Module V2** | `200x200` SPI (`SSD1681`), 2 gray levels (B/W), `0.3s` partial / `2.0s` full refresh, includes 8-pin PH2.0 harness (`SKU 12955`) | **$9.99** (Waveshare)<br>**$17.99** (Amazon) | [Amazon `B0728BJTZC` ($17.99)](https://www.amazon.com/dp/B0728BJTZC) · [Waveshare SKU 12955 ($9.99)](https://www.waveshare.com/1.54inch-e-paper-module.htm) |
| **3** | **MAX98357A I2S 3W Class-D Amp** | Filterless I2S digital audio amplifier breakout (`BCLK`, `LRCLK`, `DIN`) | **$6.88** (2-Pack)<br>**$5.95** (Adafruit 1pc) | [Amazon `B0DPJRLMDJ` ($6.88 2-Pack)](https://www.amazon.com/dp/B0DPJRLMDJ) · [Adafruit #3006 ($5.95)](https://www.adafruit.com/product/3006) |
| **4** | **1W 8Ω Mini Cavity Speaker** | Pre-wired 8Ω 1W enclosed micro speaker w/ JST-PH1.25 leads | **$6.99** (4-Pack) | [Amazon `B0D7S8FFKY` ($6.99 4-Pack)](https://www.amazon.com/dp/B0D7S8FFKY) |
| **5** | **3.7V 1000mAh `803040` LiPo Battery** | 1S pouch cell with PCM protection circuit (`40x30x8mm`). *Note: Cut JST plug and verify red=`BAT+` / black=`BAT-` polarity before soldering to XIAO pads.* | **$8.49** (1pc)<br>**$9.99** (Alt 1pc)<br>**$16.99** (4-Pack) | [Amazon `B0FRFY7KLH` ($8.49 1pc)](https://www.amazon.com/dp/B0FRFY7KLH) · [Amazon `B0FT3C1WRP` ($9.99 1pc)](https://www.amazon.com/dp/B0FT3C1WRP) · [Amazon `B0H2PKQ99D` ($16.99 4-Pack)](https://www.amazon.com/dp/B0H2PKQ99D) |
| **6** | **6x6x5mm Tactile Push Buttons** | 2 buttons used per unit: `BTN_TOP` (PTT / Wake) and `BTN_BOT` (Camera Snap / Burst) | **$6.99** (120-Pack) | [Amazon `B07VSNN9S2` ($6.99)](https://www.amazon.com/dp/B07VSNN9S2) |
| **7** | **Mini SPDT 3-Pin Slide Switch** | Hardware battery cutoff switch wired inline with LiPo `BAT+` | **$8.99** (110-Pack) | [Amazon `B0FNK8B1YV` ($8.99)](https://www.amazon.com/dp/B0FNK8B1YV) |
| **8** | **1/4W 1% Metal Film Resistor Kit** | 3x **`220 kΩ`** resistors used per unit: `220 kΩ / 220 kΩ` divider on `D4` (`VBAT` fuel gauge) + single `220 kΩ` series resistor from `5V` to `D2` (`5V VBUS` wall-brick sense) | **$6.49** (1000pc)<br>**$12.99** (1350pc) | [Amazon `B0F4P352BB` ($6.49 25-Val)](https://www.amazon.com/dp/B0F4P352BB) · [Amazon `B07P3MFG5D` ($12.99 BOJACK 50-Val)](https://www.amazon.com/dp/B07P3MFG5D) |

---

## 2. Bench Wiring & Insulation Consumables (If Not Already on Bench)

| Component | Spec & Role | Live Price | Verified Store Link |
| :--- | :--- | :--- | :--- |
| **Fermerry 30 AWG Stranded Silicone Wire Spool Set (6 Colors, 25ft Each)** | Ultra-flexible tinned copper hookup wire on 6 individual spools (`150ft` total); zero spring-back inside the compact pocket case and high-temp `200°C` silicone insulation | **$10.29** | [Amazon `B089CXFH4H` ($10.29)](https://www.amazon.com/dp/B089CXFH4H) |
| **Polyimide High-Temp Kapton Tape (4-Pack Multi-Width)** | Insulates the bottom `BAT+` / `BAT-` solder pads on the underside of the XIAO ESP32S3 and secures the `803040` LiPo pouch | **$9.99** | [Amazon `B072Z92QZ2` ($9.99)](https://www.amazon.com/dp/B072Z92QZ2) |
| **2:1 Heat-Shrink Tubing Assortment (580pc, 11 Sizes)** | Insulates the inline SPDT power switch legs and the 4x `220 kΩ` voltage-divider resistor leads | **$7.99** | [Amazon `B01MFA3OFA` ($7.99)](https://www.amazon.com/dp/B01MFA3OFA) |

---

## 3. Optional V2 Upgrade

| Component | Spec & Role | Live Price | Verified Store Link |
| :--- | :--- | :--- | :--- |
| **Official Seeed OV5640 5MP AF Camera (w/ Heatsink)** | Optional V2.2 autofocus camera upgrade built specifically for the XIAO Sense B2B header (`MPN 114993093`) | **$11.99** | [Seeed Studio ($11.99)](https://www.seeedstudio.com/OV5640-Camera-for-XIAO-ESP32S3-Sense-With-Heat-Sink-p-5739.html) |
