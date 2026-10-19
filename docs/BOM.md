# GOTCHI / SPRITE — V1 Bill of Materials (BOM) & Shopping List

All V1 hardware choices are locked for the initial two-unit prototype build (**Ryan** + **Mike / Arbiter**). Total per-unit cost is **~$58–$65** (with multipack switches, buttons, and speakers covering multiple units).

---

## 1. Core Compute, Vision & Display

| Item | Component | Part Details & Role | Est. Price | Purchase Links |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Seeed Studio XIAO ESP32S3 Sense** | Dual-core ESP32-S3, 8MB PSRAM, 8MB Flash, digital PDM mic, B2B camera connector, U.FL antenna, LiPo charger | ~$17–$24 | [Amazon (`B0C69FFVHH`)](https://www.amazon.com/dp/B0C69FFVHH) · [Seeed Studio](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html) · [The Pi Hut](https://thepihut.com/products/seeed-studio-xiao-esp32s3-sense) |
| **2** | **OV5640 5MP Autofocus Camera Module** | 2592x1944 DVP camera with integrated Voice Coil Motor (VCM) autofocus; replaces the stock fixed-focus OV2640 on the Sense B2B header | ~$10–$13 | [Amazon (`B0FVRJG44N` 2-Pack)](https://www.amazon.com/dp/B0FVRJG44N) · [Seeed Studio](https://www.seeedstudio.com/OV5640-Camera-for-XIAO-ESP32S3-Sense-With-Heat-Sink-p-5739.html) |
| **3** | **Seeed ePaper Breakout Board for XIAO** | 24-pin FPC connector, level shifting boost circuit, socketed XIAO headers, and 8-pin IO breakout header *(Note: Do NOT buy the EE04 board, which lacks the Sense B2B camera/mic header)* | ~$5 | [Seeed Studio](https://www.seeedstudio.com/ePaper-Breakout-Board-p-5804.html) · [The Pi Hut](https://thepihut.com/products/epaper-breakout-board) |
| **4** | **Waveshare 1.54" E-Paper Panel (200x200)** | Monochrome + 4-level grayscale SPI 24-pin FPC display (`SSD1681` controller, `0.3s` partial refresh). **Pro-tip:** Order the bare 24-pin glass panel (or unclip the panel from the Waveshare V2 PCB) to save 9g and 4mm thickness | ~$12–$18 | [Amazon (`B0728BJTZC`)](https://www.amazon.com/dp/B0728BJTZC) · [RobotShop](https://www.robotshop.com/products/154-e-paper-module-200x200) |

---

## 2. Audio, Power & Tactile Controls

| Item | Component | Part Details & Role | Est. Price | Purchase Links |
| :--- | :--- | :--- | :--- | :--- |
| **5** | **MAX98357A I2S 3W Class-D Amplifier** | Filterless I2S digital audio amp breakout (`BCLK`, `LRCLK`, `DIN`, `SD`) | ~$6.88 (2-Pack) | [Amazon (`B0DPJRLMDJ` 2-Pack)](https://www.amazon.com/dp/B0DPJRLMDJ) |
| **6** | **1W 8Ω Micro Speaker Capsule** | Compact pre-wired 8Ω 1W cavity/myriad micro-speaker (`15x10x3.5mm` or `20–30mm` thin capsule) | ~$6.99 (4-Pack) | [Amazon (`B0D7S8FFKY` 4-Pack)](https://www.amazon.com/dp/B0D7S8FFKY) · [Amazon (`B07GFGLX15`)](https://www.amazon.com/dp/B07GFGLX15) |
| **7** | **3.7V 800–1000mAh LiPo Battery (`803040`)** | 1S rechargeable lithium polymer pouch cell with built-in PCM protection circuit (~18g, `40x30x8mm`) | ~$9.99 (1pc) / $16.99 (4-Pack) | [Amazon (`B0FT3C1WRP` Single)](https://www.amazon.com/dp/B0FT3C1WRP) · [Amazon (`B0H2PKQ99D` 4-Pack)](https://www.amazon.com/dp/B0H2PKQ99D) |
| **8** | **6x6x5mm Momentary Tactile Push Buttons** | 2 buttons per device: **BTN_TOP** (Push-to-Talk / Deep-Sleep Wake) and **BTN_BOT** (Mode / Back / Camera Snap) | ~$6.99 (120-Pack) | [Amazon (`B07VSNN9S2`)](https://www.amazon.com/dp/B07VSNN9S2) |
| **9** | **Mini SPDT 3-Pin Slide Switch** | Hardware power disconnect / battery cutoff switch wired inline with LiPo `BAT+` | ~$8.99 (110-Pack) | [Amazon (`B0FNK8B1YV`)](https://www.amazon.com/dp/B0FNK8B1YV) |

---

## 3. Bench Consumables (Check Stash Before Ordering)

- **30 AWG Silicone-Insulated Hookup Wire** (flexible multi-strand wire for button, amp, and battery routing inside the 3D shell).
- **2mm / 3mm Heat-Shrink Tubing & Kapton Tape** (for insulating the back of the XIAO `BAT+`/`BAT-` solder pads and securing the LiPo pouch).
- **Small Copper Heatsink (`14x14x5mm`)** (included with Seeed's OV5640 module; attaches to the back of the camera/ESP32 shield for thermal dissipation during burst captures).
