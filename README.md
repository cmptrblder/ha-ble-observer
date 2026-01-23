# BLE Observer

**BLE Observer** is a Home Assistant custom integration that passively observes and classifies
Bluetooth Low Energy (BLE) devices detected by the `ble_monitor` integration.

It focuses on **behavioral observation**, **privacy safety**, and **human-readable insight** —
without claiming device or personal identity.

---

## ✨ Features

- Passively observes BLE advertisements via `ble_monitor`
- Merges multiple entities into single physical-device records
- Classifies devices by behavior (sensor, beacon, mobile, etc.)
- Provides **human-readable, non-assertive hints** such as:
  - *stationary environmental sensor*
  - *personal mobile device (rotating id)*
  - *beacon / tracker-style device*
- Confidence scoring with decay over time
- Optional promoted devices with presence, RSSI, and last-seen sensors
- Privacy-first diagnostics export (MAC masking optional)

---

## ❗ What this integration does NOT do

BLE Observer intentionally does **not**:
- Identify people
- Guess phone models
- Track movement across rooms
- Defeat MAC randomization
- Correlate rotating identifiers across days

This makes it safe, honest, and compliant with Home Assistant standards.

---

## 📦 Requirements

- Home Assistant OS or Supervised
- [`ble_monitor`](https://github.com/custom-components/ble_monitor) installed and running

BLE Observer **does not scan Bluetooth itself** — it consumes entities created by `ble_monitor`.

---

## 🔧 Installation (HACS – Custom Repository)

1. Open **HACS → Integrations**
2. Click **⋮ → Custom repositories**
3. Add: https://github.com/cmptrblder/ha-ble-observer
Category: **Integration**
4. Install **BLE Observer**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration**
7. Search for **BLE Observer**

---


## 🧪 Recommended Workflow

1. Let BLE Observer collect data over time
2. Promote a device using its fingerprint or MAC
3. Observe presence and RSSI behavior
4. Rename the promoted entity once *you* are confident

BLE Observer records observations — **you decide meaning**.

---

## 🛠 Troubleshooting

- If entities show `unavailable`, ensure `ble_monitor` entities are updating
- After adding BLE devices, wait a few minutes for rediscovery
- Use **Diagnostics → Download** to inspect observed devices

---

## 📄 License

MIT License
