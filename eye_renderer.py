"""Compoziție exclusiv din PNG-uri: iris, pupilă, reflexie fixă, pleoape."""

from dataclasses import dataclass
from functools import lru_cache
import math

from PIL import Image

import config


@dataclass(frozen=True)
class PupilAsset:
    image: Image.Image
    source_bbox: tuple
    radius: float


def _visible_bbox(image, filename):
    alpha = image.getchannel("A")
    bbox = alpha.point(
        [255 if value >= config.ALPHA_BBOX_THRESHOLD else 0 for value in range(256)]
    ).getbbox()
    if bbox is None:
        raise ValueError(f"Asset fără obiect vizibil în canalul alpha: {filename}")
    return bbox


class EyeAssets:
    """Încarcă, validează și pregătește toate imaginile o singură dată."""

    def __init__(self):
        if not 1 <= config.ALPHA_BBOX_THRESHOLD <= 255:
            raise ValueError("ALPHA_BBOX_THRESHOLD trebuie să fie între 1 și 255.")
        names = [
            config.IRIS_FILE, config.REFLECTION_FILE,
            config.HALF_EYELIDS_FILE, config.CLOSED_EYELIDS_FILE,
            *config.PUPIL_FILES.values(),
        ]
        missing = [name for name in names if not (config.ASSET_DIR / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f"Lipsesc din {config.ASSET_DIR}: {', '.join(missing)}"
            )
        loaded = {}
        for name in names:
            with Image.open(config.ASSET_DIR / name) as source:
                if source.format != "PNG" or (
                    "A" not in source.getbands() and "transparency" not in source.info
                ):
                    raise ValueError(f"Asset-ul trebuie să fie PNG cu alpha: {name}")
                source.load()
                loaded[name] = source.convert("RGBA")

        self.size = (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)
        iris_source = loaded[config.IRIS_FILE]
        iris_bbox = _visible_bbox(iris_source, config.IRIS_FILE)
        sx, sy = self.size[0] / iris_source.width, self.size[1] / iris_source.height
        # Același centru, inclusiv pentru forme cu margini transparente diferite.
        self.center = (
            round((iris_bbox[0] + iris_bbox[2]) * sx / 2),
            round((iris_bbox[1] + iris_bbox[3]) * sy / 2),
        )
        self.iris_radius = min(
            (iris_bbox[2] - iris_bbox[0]) * sx,
            (iris_bbox[3] - iris_bbox[1]) * sy,
        ) / 2
        # Fundalul este doar framebuffer-ul; toate formele provin din PNG-uri.
        self.base = Image.new("RGBA", self.size, (0, 0, 0, 255))
        self.base.alpha_composite(iris_source.resize(self.size, Image.Resampling.LANCZOS))
        self.reflection = loaded[config.REFLECTION_FILE].resize(
            self.size, Image.Resampling.LANCZOS
        )
        self.eyelids = {
            "half": loaded[config.HALF_EYELIDS_FILE].resize(
                self.size, Image.Resampling.LANCZOS
            ),
            "closed": loaded[config.CLOSED_EYELIDS_FILE].resize(
                self.size, Image.Resampling.LANCZOS
            ),
        }
        self.pupils = {}
        for name, filename in config.PUPIL_FILES.items():
            source = loaded[filename]
            bbox = _visible_bbox(source, filename)
            cropped = source.crop(bbox)
            scale = min(self.size[0] / source.width, self.size[1] / source.height)
            scale *= config.PUPIL_SCALE
            max_pulse = 1.0
            if config.SPECIAL_ANIMATIONS:
                if name == "heart":
                    max_pulse += config.HEART_PULSE_AMOUNT
                elif name == "star":
                    max_pulse += config.STAR_PULSE_AMOUNT
            safe_radius = (
                self.iris_radius - config.GAZE_EDGE_MARGIN - config.PUPIL_MIN_GAZE_ROOM
            )
            if safe_radius <= 0 or scale <= 0:
                raise ValueError("Configurația dimensiunilor pupilei este invalidă.")
            # Discul circumscris rămâne în iris, inclusiv în timpul rotației.
            scale = min(scale, 2 * safe_radius / math.hypot(*cropped.size) / max_pulse)
            # Dimensiunile pare fixează centrul exact pe același pixel la toate formele.
            size = tuple(max(2, int(value * scale / 2) * 2) for value in cropped.size)
            pupil = cropped.resize(size, Image.Resampling.LANCZOS)
            self.pupils[name] = PupilAsset(pupil, bbox, math.hypot(*size) / 2)


@lru_cache(maxsize=1)
def load_assets():
    return EyeAssets()


class EyeRenderer:
    def __init__(self, assets=None):
        self.assets = assets if assets is not None else load_assets()
        self._last_frames = {}

    @lru_cache(maxsize=config.TRANSFORM_CACHE_SIZE)
    def _transformed_pupil(self, name, width, height, angle):
        image = self.assets.pupils[name].image
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        if angle:
            image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        return image

    def _geometry(self, eye):
        asset = self.assets.pupils[eye.pupil]
        scale, angle = 1.0, 0.0
        if config.SPECIAL_ANIMATIONS:
            seconds = eye.animation_time
            if eye.pupil in ("heart", "star"):
                if eye.pupil == "heart":
                    period, amount = config.HEART_PULSE_PERIOD, config.HEART_PULSE_AMOUNT
                else:
                    period, amount = config.STAR_PULSE_PERIOD, config.STAR_PULSE_AMOUNT
                phase = round((seconds % period) / period * config.ANIMATION_PHASE_STEPS)
                scale += amount * (1 - math.cos(math.tau * phase / config.ANIMATION_PHASE_STEPS)) / 2
            elif eye.pupil == "dizzy":
                step = config.ROTATION_STEP_DEGREES
                angle = (round(seconds * config.DIZZY_ROTATION_SPEED / step) * step) % 360
        width, height = (
            max(2, round(value * scale / 2) * 2) for value in asset.image.size
        )
        radius = math.hypot(width, height) / 2
        available = max(0.0, self.assets.iris_radius - config.GAZE_EDGE_MARGIN - radius)
        dx = eye.current_x * config.MAX_GAZE_X
        dy = eye.current_y * config.MAX_GAZE_Y
        distance = math.hypot(dx, dy)
        if distance > available:
            dx *= available / distance
            dy *= available / distance
        return width, height, angle, round(dx), round(dy)

    def render(self, eye):
        width, height, angle, dx, dy = self._geometry(eye)
        signature = (eye.pupil, width, height, angle, dx, dy, eye.eyelid)
        if signature in self._last_frames:
            return self._last_frames[signature]
        frame = self.assets.base.copy()  # 1. iris fix
        pupil = self._transformed_pupil(eye.pupil, width, height, angle)
        center_x, center_y = self.assets.center
        frame.alpha_composite(pupil, (
            center_x + dx - pupil.width // 2,
            center_y + dy - pupil.height // 2,
        ))  # 2. pupilă mobilă
        frame.alpha_composite(self.assets.reflection)  # 3. reflexie FIXĂ
        if eye.eyelid != "open":
            frame.alpha_composite(self.assets.eyelids[eye.eyelid])  # 4. pleoape
        rgb = frame.convert("RGB")
        rgb._poro_cache = {}
        # Cache mic pentru cadre identice între ochi sau în perioadele de repaus.
        if len(self._last_frames) >= 4:
            self._last_frames.pop(next(iter(self._last_frames)))
        self._last_frames[signature] = rgb
        return rgb
