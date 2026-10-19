# GOTCHI / SPRITE — V1 Bill of Materials (BOM) & Live Verified Shopping List

Verified live pricing & stock as of **2026-10-18** for the two-unit prototype build (**Ryan** + **Mike / Arbiter**).
- **2-Unit Total (Cheapest Verified Mix — Seeed + Amazon):** **~$118.78** with the `OV5640` AF camera upgrade (**~$59.39/unit**), or **~$94.80** using the included stock camera (**~$47.40/unit**).
- **Breakout Update:** The discontinued Seeed ePaper Breakout (`p-5804`) is dropped. The **Waveshare 1.54" V2 Module** includes the level-shifter, boost circuit, and an 8-pin PH2.0 wire harness that wires directly to the XIAO ESP32S3 Sense (`D0/D1/D3/D5/D8/D10` + `3V3/GND`).

---

## 1. Order A — Seeed Studio Direct (or DigiKey/Mouser by MPN)

| Item | Component | MPN / SKU | Live Price (ea) | 2-Unit Qty | Verified Link |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Seeed Studio XIAO ESP32S3 Sense** (includes stock camera & PDM mic) | `113991115` | **$13.99** (In Stock) | 2 (`$27.98`) | [Seeed Studio](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html) *(Note: Amazon `B0C69FFVHH` is $23.99 with only 1 unit left)* |
| **2** | **Official Seeed OV5640 5MP Autofocus Camera for XIAO Sense (w/ Heatsink)** *(Optional Upgrade)* | `114993093` | **$11.99** (In Stock) | 2 (`$23.98`) | [Seeed Studio](https://www.seeedstudio.com/OV5640-Camera-for-XIAO-ESP32S3-Sense-With-Heat-Sink-p-5739.html) |

---

## 2. Order B — Amazon Live In-Stock Cart (Display, Audio, Power & Controls for Both Units)

| Item | Component | Pack Size | Live Amazon Price | 2-Unit Qty | Verified Amazon ASIN |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **3** | **Waveshare 1.54" E-Paper V2 Display Module (200x200 SPI + 8-Pin PH2.0 Harness)** | 1-Pack | **$17.99** (In Stock) | 2 (`$35.98`) | [Amazon (`B0728BJTZC`)](https://www.amazon.com/dp/B0728BJTZC) *(or $9.99 ea direct from Waveshare SKU 12955)* |
| **4** | **MAX98357A I2S 3W Class-D Amplifier Breakout** | **2-Pack** | **$6.88** (In Stock) | 1 pack | [Amazon (`B0DPJRLMDJ`)](https://www.amazon.com/dp/B0DPJRLMDJ) |
| **5** | **1W 8Ω Mini Cavity Speaker w/ JST-PH1.25 Leads** | **4-Pack** | **$6.99** (In Stock) | 1 pack | [Amazon (`B0D7S8FFKY`)](https://www.amazon.com/dp/B0D7S8FFKY) |
| **6** | **3.7V 1000mAh Protected LiPo Battery Pack** | **4-Pack** | **$16.99** (In Stock) | 1 pack | [Amazon (`B0H2PKQ99D`)](https://www.amazon.com/dp/B0H2PKQ99D) |
| **7** | **6x6x5mm Momentary Tactile Push Buttons (`BTN_TOP` & `BTN_BOT`)** | **120-Pack** | **$6.99** (In Stock) | 1 pack | [Amazon (`B07VSNN9S2`)](https://www.amazon.com/dp/B07VSNN9S2) |
| **8** | **Mini SPDT 3-Pin Slide Switch (Power Cutoff)** | **110-Pack** | **$8.99** (In Stock) | 1 pack | [Amazon (`B0FNK8B1YV`)](https://www.amazon.com/dp/B0FNK8B1YV) |

---

## 3. Bench Consumables (Check Stash Before Ordering)

- **30 AWG Silicone-Insulated Hookup Wire** (or use the 8-pin PH2.0 harness included in the Waveshare 1.54" V2 box).
- **2mm / 3mm Heat-Shrink Tubing & Kapton Tape** (for insulating the back of the XIAO `BAT+`/`BAT-` solder pads and securing the LiPo pouch).
