# Poro 🐾

**Poro** este un robot companion care rulează complet local (fără cloud) pe un **Raspberry Pi 4B**. Are doi ochi expresivi pe display-uri rotunde GC9A01, o limbă acționată de servo, microfon și difuzor I2S, cameră, senzor IMU BNO085 și un „creier” LLM local. Se controlează și dintr-o aplicație Android dedicată: **Poro Companion** (`PoroApp/`).

## Funcționalități

- **Ochi animați** (2× GC9A01, SPI, ~30 FPS): clipit, privire idle, urmărirea feței, pupile speciale (inimi, stele, amețit, X), pleoape sleepy/closed.
- **Voce locală**: wake word „Hey Poro” (PocketSphinx) → STT `whisper.cpp` → LLM → TTS Piper, în engleză, cu răspunsuri scurte în streaming.
- **Creier LLM local**: `llama.cpp` (`llama-server`) cu un model Qwen2.5 0.5B GGUF; comenzi directe rapide (blep, look left, emoții) fără apel LLM.
- **Vedere**: detecție de față, mișcare și analiză de scenă (OpenCV + Picamera2).
- **Corp**: limbă pe servo (PCA9685), IMU BNO085 (înclinare, scuturare, ridicare).
- **Comportament**: un singur arbitru pentru ochi, cu stări `IDLE`, `ATTENTIVE`, `LISTENING`, `THINKING`, `SPEAKING`, `HAPPY`, `CURIOUS`, `SLEEPY`, `SLEEP`, `STARTLED`.
- **Economie de energie**:
  - după 7 minute de inactivitate, ochi sleepy și un căscat;
  - după 10 minute, `SLEEP`: camera, LLM-ul și PWM-ul limbii sunt oprite, iar FPS-ul scade;
  - trezirea se face la scuturare, la „Hey Poro, wake up” sau din aplicație, cu o animație closed → sleepy → open și un voiceline.
- **Aplicație mobilă Android PoroApp** (Kotlin, Jetpack Compose, HTTP REST, Bluetooth SPP, BLE Proximitate, Fizică 2D Snax): vezi mai jos.

## Hardware

| Componentă | Detalii |
| --- | --- |
| Calculator | Raspberry Pi 4B (8 GB recomandat) |
| Ochi | 2× GC9A01 240×240 pe SPI0 (`/dev/spidev0.0`, `/dev/spidev0.1`), DC=GPIO25, RST=GPIO24 |
| Limbă | Servo pe PCA9685 (I2C `0x40`, canal 0) |
| IMU | BNO085 (I2C `0x4A`) |
| Audio | Placă I2S Google Voice HAT (microfon și difuzor) |
| Cameră | Raspberry Pi Camera (imx708) |

Pinii, rotațiile și timpii sunt în [`config.py`](config.py).

## Structura proiectului

```
main.py             # punctul de intrare (poro.service)
config.py           # toată configurația
poro_runtime.py     # RecoverySlot: repornire și suspendare a subsistemelor
PoroApp/            # Aplicația mobilă nativă Android (Kotlin & Jetpack Compose)
behavior/           # arbitrul stărilor ochilor, sleep/wake
brain/              # agent LLM, prompturi, intenții directe, memorie SQLite
voice/              # microfon, VAD, wake word, STT, TTS
vision/             # cameră, față, mișcare, analiză de scenă
body/               # limbă (servo), IMU BNO085, interpretare mișcări
hardware/           # drivere I2C, PCA9685, BNO085
mobile/             # server HTTP, Bluetooth SPP, BLE advertising
core/               # event bus
deploy/             # poro.service pentru systemd
tests/              # teste unitare
```

## Instalare pe Raspberry Pi

> Proiectul rulează cu `/usr/bin/python3`, fără virtualenv.

### 1. Dependențe de sistem

```sh
sudo apt install git cmake build-essential libopenblas-dev alsa-utils sox \
  python3-pip python3-opencv python3-picamera2 python3-dbus python3-gi \
  bluez network-manager
/usr/bin/python3 -m pip install --user --break-system-packages -r requirements.txt
```

Activează SPI și I2C cu `sudo raspi-config`. Utilizatorul care rulează Poro trebuie să facă parte din grupurile `audio`, `video`, `spi`, `i2c`, `gpio`, `bluetooth` și `netdev`.

### 2. Backend-uri native (nu sunt în repo)

Clonează în `third_party/` și compilează:

```sh
git clone https://github.com/ggml-org/llama.cpp third_party/llama.cpp
cmake -S third_party/llama.cpp -B third_party/llama.cpp/build \
  -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_BLAS=ON \
  -DGGML_BLAS_VENDOR=OpenBLAS -DLLAMA_CURL=OFF
cmake --build third_party/llama.cpp/build -j3 --target llama-server

git clone https://github.com/ggml-org/whisper.cpp third_party/whisper.cpp
cmake -S third_party/whisper.cpp -B third_party/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build third_party/whisper.cpp/build -j3 --target whisper-cli
```

### 3. Modele (nu sunt în repo)

| Fișier | Sursă |
| --- | --- |
| `models/llm/qwen2.5-0.5b-instruct-q4_0.gguf` | [Qwen/Qwen2.5-0.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) |
| `models/voice/ggml-base.en-q5_1.bin` | [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp) |
| `models/tts/en_US-lessac-medium.onnx` și `.onnx.json` | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) (`en/en_US/lessac/medium`) |

Calea fiecărui model se poate schimba în `config.py` (`LLM_MODEL_PATH`, `VOICE_STT_MODEL`, `VOICE_TTS_MODEL`).

### 4. Rulare

```sh
/usr/bin/python3 main.py                                   # normal
/usr/bin/python3 main.py --text "Hello Poro!" --duration 180   # test fără wake word
```

### 5. Pornire automată la boot

```sh
sudo cp deploy/poro.service /etc/systemd/system/poro.service
sudo systemctl daemon-reload
sudo systemctl enable --now poro.service
journalctl -u poro.service -f
```

Calea `/home/poro/Poro` și utilizatorul `poro` sunt scrise în `deploy/poro.service`. Modifică-le dacă proiectul stă în altă parte.

Mai multe detalii despre pornire, TTS și benchmark LLM sunt în [`deploy/README.md`](deploy/README.md).

## Aplicația mobilă Android „Poro Companion” (`PoroApp/`)

Aplicația nativă Android este localizată în folderul [`PoroApp/`](PoroApp/) și este construită în **Kotlin** și **Jetpack Compose** cu un design vizual inspirat din tema **Freljord / Dark Sci-Fi**.

### Funcționalități Aplicație Android
1. **Tab 1: Poro-Snax (Simulare Fizică 2D & Aruncare prin Gesturi)**:
   - Motor fizic 2D cu 22 de biscuiți Snax ce se rostogolesc real în cutie cu efecte haptice de micro-vibrație.
   - **Aruncare Snax**: Scuturarea telefonului (`G-force > 2.8g`) aruncă un Snax către robot.
   - **Blocare Proximitate**: Gestul de aruncare funcționează **doar când telefonul este aproape de robot** ($\le 1.0\text{ m}$ prin BLE sau senzorul de proximitate).
   - **Animație Pop & Explozie de Steluțe**: Snax-ul crește rapid la 780px în centrul ecranului, urmat de o explozie 360° de steluțe Freljordian albe și albastre (`star.png`) ce țâșnesc din spatele Snax-ului.
2. **Tab 2: Control & Console**:
   - **Terminal Chat LLM**: Conversație directă cu agentul AI al robotului (`/api/chat`).
   - **Acțiuni Rapide**: `👅 Blep`, `☀️ Wake`, `🌙 Sleep`, `🔇 Muted` / `🔊 Mute`.
   - **Control Emoții & Joystick Privire**: 6 butoane de emoție (`NORMAL`, `HEART`, `STAR`, `SLEEPY`, `DEAD`, `DIZZY`) și joystick circular de 210dp pentru controlul direcției ochilor (`(x, y)` vectorial).
   - **Conexiune IP & Telemetrie**: Configurare IP REST, stare Online/Offline, citiri în timp real pentru BNO085 (Roll/Pitch/Scuturare) și proximitate BLE (distanta estimată în metri).
   - **Configurare Wi-Fi (Bluetooth SPP)**: Detectare automată a robotului Poro împerecheat, scanare rețele Wi-Fi din apropiere și trimiterea credentialelor Wi-Fi prin Bluetooth RFCOMM/SPP dintr-o singură atingere.

### Rulare & Compilare Aplicație Android
 Deschide folderul `PoroApp/` în **Android Studio (Ladybug / 2024.2+)** și rulează proiectul pe orice dispozitiv Android cu **Android 8.0+ (API 26+)**.

---

### Contracte Server Mobil Raspberry Pi (`mobile/`)

Serverul mobil pornește odată cu Poro pe Raspberry Pi, dacă `MOBILE_ENABLED = True`.

#### HTTP REST (port 8000)

| Endpoint | Rol |
| --- | --- |
| `POST /api/action` | `FEED_SNAX`, `DEVICE_NEARBY`, `BLEP`, `WAKE`, `SLEEP`, `SET_EMOTION` (`normal`, `heart`, `star`, `sleepy`, `dead`, `dizzy`), `MUTE`, `UNMUTE` |
| `POST /api/gaze` | `{"x": -1..1, "y": -1..1}`, mută privirea |
| `POST /api/chat` | `{"message": "..."}`, trimite textul la LLM |
| `GET /api/telemetry` | `status`, `battery_ok`, `last_text`, `bno: {roll, pitch, shaken}` |

```sh
curl -X POST http://<IP_Poro>:8000/api/action \
  -H 'Content-Type: application/json' -d '{"action":"FEED_SNAX","parameter":null}'
```

#### Bluetooth SPP (Wi-Fi provisioning)

Serverul RFCOMM (UUID `00001101-0000-1000-8000-00805F9B34FB`, canal 1) primește `{"ssid": "...", "pass": "..."}\n` și conectează `wlan0` prin `nmcli`.

#### BLE proximitate

Poro face advertising BLE cu numele `Poro` și TxPower −59 dBm. Telefonul estimează distanța din RSSI. Flag-urile sunt LE+BR/EDR, ca Android să poată deschide și conexiunea SPP clasică.

Pentru ca `sdptool` și fallback-ul RFCOMM să funcționeze, adaugă `-C` la `ExecStart` în `bluetooth.service` (BlueZ compat), apoi rulează `sudo systemctl daemon-reload && sudo systemctl restart bluetooth`.

## Teste

```sh
/usr/bin/python3 -m unittest discover -s tests
```

Testele rulează fără hardware (cu obiecte simulate). `tests/test_body.py` are nevoie de `adafruit_blinka`, instalat pe Pi.

## Configurare utilă

Toate în [`config.py`](config.py):

- `BEHAVIOR_IDLE_SLEEPY_SECONDS` / `BEHAVIOR_IDLE_SLEEP_SECONDS`: pragurile de somn (420 s / 600 s).
- `VOICE_OUTPUT_ENABLED`: `False` oprește difuzorul, iar microfonul rămâne activ.
- `VOICE_VAD_MIN_DBFS`, `VOICE_WAKE_THRESHOLD`: sensibilitatea microfonului și a wake word-ului.
- `LLM_MODEL_PATH`, `LLM_THREADS`, `LLM_CPU_AFFINITY`: modelul și nucleele folosite.

## Licență

Proiect personal. Modelele și dependențele externe (llama.cpp, whisper.cpp, Piper, Qwen) au propriile licențe.
