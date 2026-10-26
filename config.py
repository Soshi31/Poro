"""Configurația unică pentru cei doi ochi fizici GC9A01 (BCM GPIO)."""

from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent / "assets"
DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 240
FPS = 30

SPI_BUS = 0
LEFT_SPI_DEVICE = 1  # /dev/spidev0.1
RIGHT_SPI_DEVICE = 0  # /dev/spidev0.0
LEFT_CS = 7  # CE1, pin fizic 26; gestionat exclusiv de spidev
RIGHT_CS = 8  # CE0, pin fizic 24; gestionat exclusiv de spidev
DC_PIN = 25  # pin fizic 22, comun
RST_PIN = 24  # pin fizic 18, comun
GPIO_CHIP = "/dev/gpiochip0"  # Raspberry Pi 4
SPI_MODE = 0
# Două cadre RGB565 la 30 FPS necesită cel puțin 55.3 Mbit/s pe SPI0.
# Frecvența efectivă este rotunjită de kernel; FPS rămâne o țintă.
# Reduce la 40_000_000 dacă firele lungi produc artefacte.
SPI_SPEED_HZ = 64_000_000
LEFT_ROTATION = 0  # 0, 90, 180, 270 grade
RIGHT_ROTATION = 0
# Corecție fină a întregii imagini, în jurul centrului ecranului.
# Grade pozitive = sens antiorar; negative = sens orar, privind ecranul.
LEFT_FINE_ROTATION = 6
RIGHT_FINE_ROTATION = -12
COLOR_ORDER = "BGR"  # singura setare RGB/BGR, aplicată în MADCTL
DISPLAY_INVERSION = True
CLEAR_ON_EXIT = False

# Timpi electrici, folosiți exclusiv la inițializarea hardware (secunde).
RESET_HIGH_SECONDS = 0.05
RESET_LOW_SECONDS = 0.05
RESET_RECOVERY_SECONDS = 0.15
SLEEP_OUT_SECONDS = 0.12
DISPLAY_ON_SECONDS = 0.02

PUPIL_FILES = {
    "normal": "Pupil.png",
    "happy": "Pupil_Happy.png",
    "heart": "Pupil_Heart.png",
    "star": "Pupil_Star.png",
    "dizzy": "Pupil_Dizzy.png",
    "x": "Pupil_X.png",
}
IRIS_FILE = "Iris.png"
REFLECTION_FILE = "Reflection.png"
HALF_EYELIDS_FILE = "Eyelids_Half.png"
CLOSED_EYELIDS_FILE = "Eyelids_Closed.png"
# Ignoră zgomotul alpha aproape invizibil la calculul geometriei.
# PNG-urile și alpha obiectului păstrat nu sunt modificate.
ALPHA_BBOX_THRESHOLD = 8  # 1 = orice pixel cu alpha nenul
PUPIL_SCALE = 1.0
PUPIL_MIN_GAZE_ROOM = 12.0  # spațiu păstrat și pentru formele mari
GAZE_EDGE_MARGIN = 3.0
MAX_GAZE_X = 32.0  # pixeli; limita reală depinde de forma pupilei
MAX_GAZE_Y = 26.0
GAZE_SMOOTHING = 12.0  # rată exponențială / secundă

AUTO_BLINK = True
BLINK_MIN_INTERVAL = 2.5
BLINK_MAX_INTERVAL = 6.0
DOUBLE_BLINK_CHANCE = 0.15
DOUBLE_BLINK_PAUSE_MIN = 0.10
DOUBLE_BLINK_PAUSE_MAX = 0.20
BLINK_OPEN_TO_HALF = 0.035
BLINK_HALF_TO_CLOSED = 0.035
BLINK_CLOSED_HOLD = 0.045
BLINK_CLOSED_TO_HALF = 0.035
BLINK_HALF_TO_OPEN = 0.035
WAKE_CLOSED_HOLD = 0.45
WAKE_HALF_HOLD = 1.25

IDLE_ENABLED = True
IDLE_TARGET_TIMEOUT = 2.0
IDLE_PAUSE_MIN = 1.0
IDLE_PAUSE_MAX = 3.0
IDLE_GAZE_X = 0.45
IDLE_GAZE_Y = 0.28
IDLE_CENTER_CHANCE = 0.25
IDLE_MICROSACCADE_CHANCE = 0.65
IDLE_MICROSACCADE_AMOUNT = 0.045
IDLE_MICROSACCADE_PAUSE_MIN = 0.25
IDLE_MICROSACCADE_PAUSE_MAX = 0.65

TRACKING_DEADZONE = 0.06  # coordonate normalizate
TRACKING_SENSITIVITY_X = 1.0
TRACKING_SENSITIVITY_Y = 1.0
TRACKING_MIRROR_X = False
TRACKING_SMOOTHING = 16.0  # filtrarea target-ului, rată / secundă

SPECIAL_ANIMATIONS = True
HEART_PULSE_AMOUNT = 0.05
HEART_PULSE_PERIOD = 1.4
STAR_PULSE_AMOUNT = 0.04
STAR_PULSE_PERIOD = 1.8
DIZZY_ROTATION_SPEED = 35.0  # grade / secundă
ANIMATION_PHASE_STEPS = 60
ROTATION_STEP_DEGREES = 3.0
TRANSFORM_CACHE_SIZE = 192

# Percepție: camera rămâne activă; detecția consumă doar ultimul cadru mic.
CAMERA_INDEX = 0
CAMERA_MAIN_SIZE = (1280, 960)
CAMERA_DETECTION_SIZE = (320, 240)  # lores YUV420, micșorat de ISP
CAMERA_FPS = 30
CAMERA_ROTATION = 0  # 0 sau 180; imagine dreaptă ÎNAINTE de detecție
CAMERA_FRAME_TIMEOUT = 3.0  # eroare explicită dacă fluxul se oprește

FACE_DETECTION_FPS = 8
FACE_CASCADE_PATH = Path("/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml")
FACE_SCALE_FACTOR = 1.15
FACE_MIN_NEIGHBORS = 5
FACE_CONFIRM_DETECTIONS = 2  # ținta nouă trebuie văzută în detecții consecutive
FACE_MIN_SIZE = (30, 30)  # pixeli în fluxul mic
FACE_OPENCV_THREADS = 1
FACE_EQUALIZE_HIST = True
FACE_INVERT_X = True  # invert_x: inversează doar direcția țintei
FACE_INVERT_Y = False  # invert_y: inversează doar direcția țintei
FACE_TARGET_HOLD_SECONDS = 1.5
FACE_TARGET_DEADBAND = 0.025  # ignoră tremurul față de ultima țintă acceptată
VISION_LOG_INTERVAL = 3.0
# Sensibilitatea/deadzone centrală/smoothing folosesc TRACKING_* de mai sus.

# Perception: FAST este independent de consumatori și de procesul SLOW.
PERCEPTION_FAST_FPS = 20
PERCEPTION_EVENT_CAPACITY = 64  # per abonat; la overflow se elimină cel mai vechi
PERCEPTION_PEOPLE_TTL = 0.75  # vizibilitate actuală, distinctă de holding-ul ochilor
PERSON_POSITION_INTERVAL = 0.25
MOTION_ENABLED = True
MOTION_FPS = 10
MOTION_PIXEL_THRESHOLD = 20
MOTION_MIN_FRACTION = 0.015
MOTION_EVENT_INTERVAL = 1.0
AI_FRAME_MAX_SIZE = (640, 480)
AI_FRAME_TIMEOUT = 1.0
SLOW_VISION_INTERVAL = 0.0  # 0 = numai la request_slow_analysis()
SLOW_VISION_TIMEOUT = 3.0  # procesul lent se repornește dacă analiza se blochează
SLOW_STARTUP_TIMEOUT = 10.0  # pornirea procesului/importurile au un buget separat
SLOW_RESULT_TTL = 12.0  # rezultatele vechi nu apar ca obiecte vizibile
SLOW_ANALYZERS = ("vision.analyzers:SceneMetricsAnalyzer",)

# Voice local. ALSA plug convertește placa I2S 48kHz/S32_LE în PCM16/16kHz.
VOICE_ROOT = Path(__file__).resolve().parent
VOICE_CAPTURE_DEVICE = "plughw:CARD=sndrpigooglevoi,DEV=0"
VOICE_PLAYBACK_DEVICE = "plughw:CARD=sndrpigooglevoi,DEV=0"
VOICE_SAMPLE_RATE = 16000
VOICE_CAPTURE_CHANNELS = 2
VOICE_MIC_CHANNEL = 0  # canalul cu semnal, verificat pe hardware
VOICE_MIC_GAIN = 1.0
VOICE_FRAME_MS = 30
VOICE_AUDIO_QUEUE_FRAMES = 32
VOICE_CAPTURE_TIMEOUT = 3.0
VOICE_VAD_MODE = 2  # 0 permisiv ... 3 strict
VOICE_VAD_MIN_DBFS = -43.0
VOICE_PRE_ROLL_SECONDS = 0.45
VOICE_START_FRAMES = 2
VOICE_END_SILENCE_SECONDS = 0.55
VOICE_MIN_SPEECH_SECONDS = 0.25
VOICE_MAX_UTTERANCE_SECONDS = 8.0
WAKE_WORD = "Hei Poro"  # pronunțat identic cu «Hey Poro»; în dicționarul CMU "hey" există deja
VOICE_WAKE_WORD = WAKE_WORD
# Variante locale de pronunție pentru fiecare cuvânt (CMU/PocketSphinx).
VOICE_WAKE_PHONEMES = (
    ("HH EY", "HH AY", "HH EH"),
    ("P AO R OW", "P OW R OW", "P AO R AH", "P ER OW"),
)
VOICE_WAKE_THRESHOLD = 1e-24  # mai mic = mai permisiv; calibrare pe voce reală
VOICE_WAKE_FIRST_THRESHOLD = 1e-14  # primul cuvânt scurt cere prag mai strict
VOICE_WAKE_MAX_GAP_SECONDS = 1.0
VOICE_WAKE_COMMAND_TIMEOUT = 6.0
VOICE_WAKE_ACK = ""  # trezire silențioasă (ochii trec în LISTENING fără risc de ecou audio)
VOICE_MIN_COMMAND_SECONDS = 0.25
VOICE_ECHO_GUARD_SECONDS = 0.35
VOICE_STT_BINARY = VOICE_ROOT / "third_party/whisper.cpp/build/bin/whisper-cli"
VOICE_STT_MODEL = VOICE_ROOT / "models/voice/ggml-base.en-q5_1.bin"
VOICE_STT_LANGUAGE = "en"
VOICE_STT_THREADS = 3
VOICE_STT_NORMALIZE_PEAK = 0.8  # amplificare numai pe fraza trimisă la STT
VOICE_STT_MAX_GAIN = 16.0
VOICE_STT_AUDIO_CONTEXT = 512  # 10,24 s; peste limita de 8 s a segmentului
VOICE_STT_TIMEOUT = 45.0
VOICE_STT_SINGLE_WORD_CORRECTIONS = {
    "hi": "Hello!",
    "hey": "Hello!",
    "hello": "Hello!",
    "blep": "Do a blep!",
    "tongue": "Stick out your tongue!",
    "sleep": "Go to sleep!",
    "wake": "Wake up!",
    "sarut": "Salut!",
}
VOICE_STT_QUEUE_SIZE = 1
VOICE_TEXT_QUEUE_SIZE = 8
VOICE_TTS_VOICE = "en"
VOICE_TTS_SPEED = 165
VOICE_TTS_AMPLITUDE = 65  # eSpeak: 0..200
VOICE_OUTPUT_ENABLED = True  # False = mod silențios: microfon/STT active, difuzor oprit
VOICE_TTS_BACKEND = "piper"  # "piper" sau "espeak"
VOICE_TTS_MODEL = VOICE_ROOT / "models/tts/en_US-lessac-medium.onnx"
VOICE_TTS_LENGTH_SCALE = 0.90  # < 1 = vorbire sprintenă
VOICE_TTS_PITCH_CENTS = 140  # voce drăgălașă de Poro
VOICE_TTS_THREADS = 2
# Profiluri de voce: (multiplicator durată, delta pitch în cenți, volum).
VOICE_TTS_EMOTIONS = {
    "neutral": (1.0, 0, 1.0),
    "happy": (0.94, 70, 1.0),
    "excited": (0.88, 120, 1.0),
    "curious": (0.98, 90, 1.0),
    "sleepy": (1.15, -80, 0.85),
    "sad": (1.12, -60, 0.9),
    "surprised": (0.92, 150, 1.0),
}
VOICE_TTS_MAX_CHARS = 500
VOICE_TTS_QUEUE_SIZE = 3
VOICE_TTS_TIMEOUT = 180.0  # textul maxim de 500 caractere pe Pi 4 poate dura > 60 s

# Corp: aceeași magistrală board.SCL/SDA ca hardware_tests/bno085.py.
BODY_IMU_ADDRESS = 0x4A
BODY_PCA_ADDRESS = 0x40
BODY_POLL_HZ = 50
BODY_REPORT_INTERVAL_US = 50_000  # 20 Hz: suficient semantic, mai puțin trafic I2C
BODY_I2C_READ_PAUSE_SECONDS = 0.001
BODY_SENSOR_TIMEOUT = 1.0
BODY_WARMUP_SECONDS = 1.2
# Robot: +X dreapta, +Y în față, +Z sus. ±1/2/3 = axele senzorului.
BODY_AXIS_MAP = (1, 2, 3)  # Z sus verificat; X/Y se verifică prin înclinare
BODY_SMOOTHING_SECONDS = 0.12
BODY_GRAVITY_SMOOTHING_SECONDS = 0.18
BODY_TILT_ENTER_DEG = 25.0
BODY_TILT_EXIT_DEG = 15.0
BODY_TILT_DWELL_SECONDS = 0.25
BODY_TILT_COOLDOWN_SECONDS = 1.0
BODY_UPSIDE_ENTER_DEG = 145.0
BODY_UPSIDE_EXIT_DEG = 125.0
BODY_MOVE_ACCEL_ENTER = 0.65  # m/s², fără gravitație
BODY_MOVE_ACCEL_EXIT = 0.30
BODY_MOVE_GYRO_ENTER = 0.25  # rad/s
BODY_MOVE_GYRO_EXIT = 0.12
BODY_MOVE_START_SECONDS = 0.12
BODY_MOVE_STOP_SECONDS = 0.7
BODY_SHAKE_ACCEL = 4.0
BODY_SHAKE_WINDOW_SECONDS = 0.8
BODY_SHAKE_MIN_PEAKS = 3
BODY_SHAKE_COOLDOWN_SECONDS = 2.0
BODY_LIFT_ACCEL = 0.9
BODY_LIFT_BRAKE_ACCEL = 0.5
BODY_LIFT_MIN_IMPULSE = 0.12  # m/s, estimare pe fereastră scurtă
BODY_LIFT_WINDOW_SECONDS = 2.0
BODY_LIFT_SETTLE_SECONDS = 0.25
BODY_PUT_DOWN_SETTLE_SECONDS = 0.6
BODY_LIFT_COOLDOWN_SECONDS = 1.5
BODY_EVENT_CAPACITY = 64

# Limbă: sens confirmat pe montaj. Numai hardware/body lucrează cu unghiuri.
TONGUE_CHANNEL = 0
TONGUE_PWM_HZ = 50
TONGUE_MIN_PULSE_US = 750  # valorile implicite ale ServoKit-ului existent
TONGUE_MAX_PULSE_US = 2250
TONGUE_MIN_ANGLE = 0.0
TONGUE_MAX_ANGLE = 175.0  # NU ajunge la 180 pe montajul actual
TONGUE_IN_ANGLE = 175.0
TONGUE_OUT_ANGLE = 0.0
TONGUE_BLEP_FRACTION = 0.5
TONGUE_SPEED_DEG_PER_SECOND = 140.0
TONGUE_BLEP_HOLD_SECONDS = 0.25
TONGUE_DOUBLE_BLEP_GAP_SECONDS = 0.25
TONGUE_ACTION_QUEUE_SIZE = 4
TONGUE_RELEASE_IDLE_SECONDS = 1.0  # None = menține PWM

# Behavior: priorități și durate. EyeSystem rămâne singurul motor de blink.
BEHAVIOR_COMMAND_QUEUE_SIZE = 32
BEHAVIOR_COMMANDS_PER_TICK = 16
BEHAVIOR_TEXT_QUEUE_SIZE = 8
BEHAVIOR_EVENTS_PER_TICK = 32
BEHAVIOR_EVENT_MAX_AGE = 2.0
BEHAVIOR_STARTLED_SECONDS = 1.8
BEHAVIOR_CURIOUS_SECONDS = 2.0
BEHAVIOR_HAPPY_SECONDS = 1.5
BEHAVIOR_THINKING_TIMEOUT = 15.0
BEHAVIOR_IDLE_SLEEPY_SECONDS = 420.0  # 7 minute de inactivitate -> ochi sleepy + căscat
BEHAVIOR_IDLE_SLEEP_SECONDS = 600.0   # 10 minute de inactivitate -> deep sleep cu economisire energie
BEHAVIOR_SLEEPY_YAWN_TEXT = "Yaaawn... I am getting so sleepy..."
BEHAVIOR_WAKE_VOICELINE = "Yaaawn! Good morning! I am awake and ready to play!"
BEHAVIOR_WAKE_MIN_SECONDS = 1.8
BEHAVIOR_WAKE_MAX_WAIT_SECONDS = 8.0
SLEEP_FPS = 10

# Creier local (llama.cpp + GGUF). Schimbarea modelului nu cere modificări în brain/.
LLM_SERVER_BINARY = VOICE_ROOT / "third_party/llama.cpp/build/bin/llama-server"
LLM_MODEL_PATH = VOICE_ROOT / "models/llm/qwen2.5-0.5b-instruct-q4_0.gguf"
LLM_HOST = "127.0.0.1"
LLM_PORT = 8081
LLM_CONTEXT_SIZE = 1024
LLM_THREADS = 3
LLM_CPU_AFFINITY = (1, 2, 3)  # nucleele 1-3 pentru llama-server; main/STT/TTS pot folosi toate nucleele libere
LLM_NICE = 0  # prioritate normală pentru a nu întrerupe barierele OpenMP
LLM_BATCH_SIZE = 256
LLM_MAX_TOKENS = 48
LLM_PLAIN_MAX_TOKENS = 32  # conversație în streaming (1 propoziție completă, oprită la primul punct)
LLM_TEMPERATURE = 0.0
LLM_TOP_P = 0.9
LLM_REPEAT_PENALTY = 1.05
LLM_STARTUP_TIMEOUT = 120.0
LLM_REQUEST_TIMEOUT = 120.0
LLM_MAX_RESPONSE_BYTES = 64_000

BRAIN_PERSONALITY_FILE = VOICE_ROOT / "brain/personality.txt"
BRAIN_LORE_MAX_CHARS = 280
BRAIN_MEMORY_PATH = VOICE_ROOT / "brain/memory.sqlite3"
BRAIN_CONTEXT_MAX_CHARS = 780
BRAIN_HISTORY_TURNS = 1
BRAIN_MAX_ACTIONS = 4
BRAIN_MAX_TOOL_ROUNDS = 2
BRAIN_INPUT_QUEUE_SIZE = 2
BRAIN_RESULT_QUEUE_SIZE = 4
BRAIN_EVENT_HISTORY = 8
BRAIN_MAX_USER_CHARS = 500
BRAIN_MAX_SPEECH_CHARS = 220
BRAIN_MAX_MEMORY_CHARS = 300
BRAIN_MEMORY_LIMIT = 1000
BRAIN_CONVERSATION_LIMIT = 24       # replici; termen scurt, inclusiv între restarturi
BRAIN_EVENT_MEMORY_LIMIT = 500     # doar evenimente semantice, nu cadre video
BRAIN_EVENT_MAX_CHARS = 500
BRAIN_VISUAL_BACKEND = "vision.understanding:StructuredVisionBackend"
BRAIN_VISUAL_TIMEOUT = 16.0
BRAIN_VISUAL_RESULT_MAX_CHARS = 2000
BRAIN_SNAPSHOT_DIR = VOICE_ROOT / "snapshots"
BRAIN_MAX_SNAPSHOTS = 100
BRAIN_SNAPSHOT_JPEG_QUALITY = 85

# Orchestrare: subsistemele recuperabile se repornesc în worker-e separate.
SYSTEM_HEALTH_INTERVAL_SECONDS = 1.0
SYSTEM_RECOVERY_INITIAL_SECONDS = 2.0
SYSTEM_RECOVERY_MAX_SECONDS = 30.0
SYSTEM_SHUTDOWN_TIMEOUT = 20.0
SYSTEM_STATUS_LOG_INTERVAL = 10.0

# Mobile Companion App (Android <-> Raspberry Pi 4B): HTTP REST, Bluetooth SPP, BLE Advertising.
MOBILE_ENABLED = True
MOBILE_HTTP_HOST = "0.0.0.0"
MOBILE_HTTP_PORT = 8000
MOBILE_BT_SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"
MOBILE_BT_SPP_CHANNEL = 1
MOBILE_BLE_NAME = "Poro"
MOBILE_BLE_TX_POWER_DBM = -59
MOBILE_BLE_PATH_LOSS_N = 2.0
