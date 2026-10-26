"""Camera Picamera2 reală, fără fereastră și fără coadă de cadre vechi."""

from dataclasses import dataclass
from concurrent.futures import Future
import io
import logging
import math
from threading import Lock
import time

import numpy as np

import config


@dataclass(frozen=True)
class CameraFrame:
    sequence: int
    captured_at: float  # time.monotonic() la primirea cadrului
    gray: np.ndarray  # copie proprie, read-only; nu reține bufferul camerei


@dataclass(frozen=True)
class AIFrame:
    sequence: int
    captured_at: float
    rgb: np.ndarray

    def metadata(self):
        height, width = self.rgb.shape[:2]
        return {"sequence": self.sequence, "captured_at": self.captured_at,
                "clock": "monotonic", "width": width, "height": height, "format": "RGB"}

    def jpeg_bytes(self, quality=85):
        from PIL import Image
        output = io.BytesIO()
        Image.fromarray(self.rgb).save(output, format="JPEG", quality=quality)
        return output.getvalue()


class Camera:
    """Unicul proprietar al camerei; latest_frame() nu așteaptă captura.

    Callback-ul Picamera2 copiază numai luminanța fluxului lores.
    Consumatorii pot citi aceeași fotografie fără a deschide alte camere.
    Fluxul main rămâne disponibil pentru extinderea viitoare a percepției.
    """

    def __init__(self):
        self._camera = None
        self._lock = Lock()
        self._latest = None
        self._error = None
        self._sequence = 0
        self._started_at = None
        self._ai_request = None

    def start(self):
        if self._camera is not None:
            raise RuntimeError("Camera este deja pornită.")
        if config.CAMERA_ROTATION not in (0, 180):
            raise ValueError("CAMERA_ROTATION trebuie să fie 0 sau 180.")
        if not math.isfinite(config.CAMERA_FPS) or config.CAMERA_FPS <= 0:
            raise ValueError("CAMERA_FPS trebuie să fie pozitiv și finit.")
        if not math.isfinite(config.CAMERA_FRAME_TIMEOUT) or config.CAMERA_FRAME_TIMEOUT <= 0:
            raise ValueError("CAMERA_FRAME_TIMEOUT trebuie să fie pozitiv și finit.")
        for size in (config.CAMERA_MAIN_SIZE, config.CAMERA_DETECTION_SIZE):
            if len(size) != 2 or any(not isinstance(v, int) or v <= 0 or v % 2 for v in size):
                raise ValueError("Dimensiunile camerei trebuie să fie întregi pozitive pare.")
        if any(low > high for low, high in zip(config.CAMERA_DETECTION_SIZE, config.CAMERA_MAIN_SIZE)):
            raise ValueError("Fluxul de detecție trebuie să fie cel mult cât fluxul main.")
        from libcamera import Transform, controls
        from picamera2 import Picamera2

        self._latest = self._error = None
        self._sequence = 0
        self._camera = Picamera2(camera_num=config.CAMERA_INDEX)
        try:
            rotate = config.CAMERA_ROTATION == 180
            camera_config = self._camera.create_video_configuration(
                main={"size": config.CAMERA_MAIN_SIZE, "format": "RGB888"},
                lores={"size": config.CAMERA_DETECTION_SIZE, "format": "YUV420"},
                transform=Transform(hflip=rotate, vflip=rotate),
                controls={"FrameRate": config.CAMERA_FPS},
                buffer_count=4,
                queue=False,
            )
            self._camera.configure(camera_config)
            self._lores_size = self._camera.camera_configuration()["lores"]["size"]
            if "AfMode" in self._camera.camera_controls:
                self._camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
            self._camera.post_callback = self._on_frame
            self._started_at = time.monotonic()
            self._camera.start(show_preview=False)
            logging.info("Camera pornită: main=%s, detecție=%s, țintă %.1f FPS, fără preview",
                         config.CAMERA_MAIN_SIZE, self._lores_size, config.CAMERA_FPS)
        except BaseException:
            self.close()
            raise
        return self

    def _on_frame(self, request):
        try:
            from picamera2 import MappedArray

            captured_at = time.monotonic()
            width, height = self._lores_size
            # YUV420: primele height rânduri sunt Y; eliminăm padding-ul stride.
            with MappedArray(request, "lores", write=False) as mapped:
                gray = mapped.array[:height, :width].copy()
            gray.flags.writeable = False
            with self._lock:
                self._sequence += 1
                self._latest = CameraFrame(self._sequence, captured_at, gray)
                sequence = self._sequence
                ai_request = self._ai_request
                self._ai_request = None
            if ai_request is not None:
                try:
                    # RGB888 Picamera2 livrează B,G,R în memorie. Copiere numai
                    # la cerere; redimensionarea/JPEG se fac în thread-ul apelant.
                    rgb = request.make_array("main")[:, :, ::-1].copy()
                    rgb.flags.writeable = False
                    ai_request.set_result(AIFrame(sequence, captured_at, rgb))
                except Exception as error:
                    ai_request.set_exception(error)
        except Exception as error:
            # Nu lăsăm o excepție să omoare silențios event loop-ul Picamera2.
            with self._lock:
                self._error = error

    def latest_frame(self):
        with self._lock:
            return self._latest

    def capture_frame_for_ai(self, timeout=None):
        """Așteaptă următorul cadru color, doar la cerere. Nu apela din eye loop."""
        from PIL import Image
        timeout = config.AI_FRAME_TIMEOUT if timeout is None else timeout
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout-ul capturii AI trebuie să fie pozitiv și finit")
        size = config.AI_FRAME_MAX_SIZE
        if len(size) != 2 or any(not isinstance(v, int) or v <= 0 for v in size):
            raise ValueError("AI_FRAME_MAX_SIZE trebuie să conțină doi întregi pozitivi")
        self.check_health()
        with self._lock:
            if self._started_at is None:
                raise RuntimeError("Camera nu este pornită")
            if self._ai_request is None:
                self._ai_request = Future()
            pending = self._ai_request  # cererile simultane împart următoarea captură
        frame = pending.result(timeout=timeout)
        image = Image.fromarray(frame.rgb)
        image.thumbnail(size, Image.Resampling.BILINEAR)
        rgb = np.array(image)
        rgb.flags.writeable = False
        return AIFrame(frame.sequence, frame.captured_at, rgb)

    def check_health(self):
        with self._lock:
            error, frame = self._error, self._latest
        if error is not None:
            raise RuntimeError("Captura Picamera2 a eșuat.") from error
        if self._started_at is not None:
            last_frame_at = frame.captured_at if frame is not None else self._started_at
            if time.monotonic() - last_frame_at > config.CAMERA_FRAME_TIMEOUT:
                raise RuntimeError("Camera nu mai livrează cadre; verifică panglica/conexiunea CSI.")

    def close(self):
        with self._lock:
            pending, self._ai_request = self._ai_request, None
            self._started_at = None
        if pending is not None:
            pending.set_exception(RuntimeError("Camera s-a închis înainte de captura AI"))
        if self._camera is not None:
            try:
                self._camera.close()
            finally:
                self._camera = None
                self._started_at = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
