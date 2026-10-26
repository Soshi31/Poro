# ❄️ Poro - Native Android Companion App

An Android companion application built in **Kotlin** and **Jetpack Compose** for controlling a physical Raspberry Pi 4B robot named **Poro**, featuring a **Freljord / Dark Sci-Fi theme**, **2D physics Snax simulation**, **BLE proximity detection**, **Bluetooth SPP Wi-Fi provisioning**, and **REST API telemetry & control**.

---

## 🌟 Highlights & Features

### 🍪 1. Tab 1: Poro-Snax (2D Physics & Gesture Toss)
- **Interactive Physics Engine**: Real-time 2D rigid-body physics with 22 biscuits bouncing inside the cereal box frame.
- **Micro-Vibration Feedback**: Micro-haptic rattle effects when biscuits collide against box walls or each other.
- **Snax Toss Gesture**: Throw a Snax to Poro by tilting/shaking your phone (`G-Force > 2.8g`).
- **Proximity Lock**: Snax toss is activated **only when the phone is within 1.0m** of the robot (via BLE or Hardware Proximity sensor).
- **Celebration Burst**: Fast Snax pop-up accompanied by a 360° burst of **36 Freljordian ice star particles** (`star.png`) emerging from behind the Snax.

### 🎮 2. Tab 2: Control & Console
1. **Terminal Chat LLM**: Real-time chat interface communicating with Poro's AI agent on Raspberry Pi (`/api/chat`).
2. **Quick Actions**: Instant REST commands (`BLEP`, `WAKE`, `SLEEP`, `MUTE` / `UNMUTE`) with visual feedback.
3. **Control Emoții & Privire**:
   - **6 Emotion Buttons**: `NORMAL`, `HEART`, `STAR`, `SLEEPY`, `DEAD`, `DIZZY`.
   - **210dp Vector Eye Joystick**: Drag-to-look circular joystick sending normalized `(x, y)` gaze vectors (`vector magnitude <= 1.0`).
4. **Conexiune Freljord (IP Setup)**: Real-time REST polling loop (`/api/telemetry`) showing IP address setup, Online/Offline status badge, and battery health.
5. **Configurare Wi-Fi (Bluetooth)**:
   - Automatic detection and pairing status for Poro.
   - **Wi-Fi Scanner**: Automatic scan and chip selection of nearby Wi-Fi SSIDs (`WifiManager`).
   - One-tap Wi-Fi credential sender over **Bluetooth RFCOMM/SPP**.
6. **Telemetrie Poro & Senzori Telefon**: Real-time AI status, BNO085 Roll/Pitch/Shaken sensor data, BLE RSSI, estimated distance (meters), and phone G-Force.

---

## 🎨 Visual Theme (Freljord / Dark Sci-Fi)

- **Surface Color**: Darkwood (`#1E1512`)
- **Primary Accent**: True Ice Cyan (`#00E5FF`)
- **Background**: `#080D14` with custom Freljord background image (`backround.jpg`)
- **Shape System**: Angular `CutCornerShapes` for a League of Legends / Freljordian aesthetic.

---

## 🛠️ Architecture & Tech Stack

- **Language**: Kotlin 1.9+
- **UI Framework**: Jetpack Compose (Material3)
- **HTTP & REST**: OkHttp3, Gson
- **Networking**: Asynchronous Coroutines, StateFlow
- **Sensors**: `SensorManager` (Accelerometer & Hardware Proximity)
- **Bluetooth**: `BluetoothLeScanner` (BLE Proximity), `BluetoothSocket` (RFCOMM Channel 1 Fallback SPP)

---

## 📡 REST API & Network Contracts

The app connects to Poro's REST API running on port `8000`:

| Endpoint | Method | Payload / Parameters | Description |
| :--- | :--- | :--- | :--- |
| `/api/action` | `POST` | `{"action": "FEED_SNAX\|BLEP\|WAKE\|SLEEP\|MUTE\|UNMUTE"}` | Triggers physical robot actions |
| `/api/gaze` | `POST` | `{"x": float, "y": float}` | Updates eye look-at vector |
| `/api/chat` | `POST` | `{"prompt": "string"}` | Sends text message to Poro's LLM |
| `/api/telemetry` | `GET` | — | Returns JSON telemetry (BNO085 orientation, AI status, battery status) |

---

## 🚀 Building & Running

1. Clone this repository:
   ```bash
   git clone https://github.com/Soshi31/Poro.git
   ```
2. Open the project in **Android Studio (Ladybug / 2024.2+)**.
3. Connect an Android device running **Android 8.0+ (API 26+)** with Bluetooth & Location enabled.
4. Build and run:
   ```bash
   ./gradlew assembleDebug
   ```

---

## 📄 License

Developed for the **Poro Physical Robot Project**. All rights reserved.
