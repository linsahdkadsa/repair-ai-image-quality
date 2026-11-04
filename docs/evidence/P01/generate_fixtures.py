"""生成 P01 的最小合成样本，不写入真实业务图片或个人数据。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "tests" / "fixtures" / "images"


def save(path: Path, rgb: np.ndarray, exif: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    image = Image.fromarray(arr, "RGB")
    if exif:
        exif_data = image.getexif()
        exif_data[0x010F] = "RepairAiImage synthetic camera"
        exif_data[0x0110] = "P01 fixture"
        image.save(path, quality=94, exif=exif_data.tobytes())
    else:
        image.save(path)


def maze(height: int, width: int) -> np.ndarray:
    rng = np.random.RandomState(17)
    noise = rng.randn(height, width)
    freq = np.fft.fft2(noise)
    fy = np.fft.fftfreq(height)[:, None]
    fx = np.fft.fftfreq(width)[None, :]
    radius = np.hypot(fy, fx) / 0.5
    band = (radius >= 0.22) & (radius <= 0.48)
    labyrinth = np.real(np.fft.ifft2(freq * band))
    labyrinth = np.tanh(2.5 * labyrinth / max(float(labyrinth.std()), 1e-6))
    labyrinth = labyrinth / max(float(np.abs(labyrinth).max()), 1e-6)
    yy, xx = np.mgrid[0:height, 0:width] / max(height, width)
    surface = 0.58 + 0.08 * np.sin(xx * 8.0) * np.cos(yy * 6.0)
    surface -= (np.abs(xx - 0.62) < 0.008) * 0.16
    clean = np.dstack((surface * 0.96, surface, surface * 1.04))
    return np.clip(clean + labyrinth[..., None] * 0.06, 0, 1).astype(np.float32)


def clean_scene(height: int = 256, width: int = 320) -> np.ndarray:
    image = np.zeros((height, width, 3), np.float32)
    image[:] = (0.28, 0.42, 0.62)
    cv2.rectangle(image, (20, 22), (150, 220), (0.75, 0.68, 0.42), -1)
    cv2.circle(image, (235, 92), 58, (0.18, 0.68, 0.38), -1)
    cv2.line(image, (12, 235), (308, 20), (0.94, 0.90, 0.82), 5)
    return image


def color_edit(source: np.ndarray, cast: tuple[float, float, float]) -> np.ndarray:
    edit = np.clip(source * np.array(cast, np.float32), 0, 1)
    edit[88:178, 198:294] = (0.12, 0.34, 0.86)
    return edit


def make_fixtures() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    d01 = maze(256, 256)
    d02 = np.full((256, 256, 3), 0.58, dtype=np.float32)
    save(OUT / "D01_mazey.png", d01)
    save(OUT / "D02_clean.png", d02)

    # 大图/EXIF 样本用于验证实拍保护门，不代表真实相机数据。
    large = np.zeros((2200, 3300, 3), np.float32)
    yy, xx = np.mgrid[0:2200, 0:3300]
    large[..., 0] = 0.35 + 0.2 * xx / 3300
    large[..., 1] = 0.42 + 0.16 * yy / 2200
    large[..., 2] = 0.56 + 0.12 * (xx + yy) / 5500
    save(OUT / "D03_large_exif.jpg", large, exif=True)

    low = maze(128, 128)
    scaled = cv2.resize(low, (512, 512), interpolation=cv2.INTER_NEAREST)
    save(OUT / "D04_scaled_texture.png", scaled)

    source = clean_scene()
    edit = color_edit(source, (1.04, 0.95, 1.03))
    save(OUT / "C01_source.png", source)
    save(OUT / "C01_edit.png", edit)

    grey = np.full_like(source, (0.62, 0.62, 0.62))
    grey_edit = grey.copy()
    grey_edit[55:190, 40:170] = (0.22, 0.62, 0.32)
    save(OUT / "C02_grey_source.png", grey)
    save(OUT / "C02_grey_edit.png", grey_edit)

    warm = np.clip(source * (1.18, 1.02, 0.78), 0, 1)
    save(OUT / "C03_intentional_grade_source.png", source)
    save(OUT / "C03_intentional_grade_edit.png", warm)

    local_edit = edit.copy()
    local_edit[70:180, 70:220] = np.clip(local_edit[70:180, 70:220] * (0.72, 1.08, 1.15), 0, 1)
    save(OUT / "P01_local_source.png", source)
    save(OUT / "P01_local_edit.png", local_edit)

    save(OUT / "B01_01.png", d01)
    save(OUT / "B01_02.png", d02)
    save(OUT / "E01_noisy.png", d01)
    save(OUT / "E01_truth.png", d02)

    product = np.full((400, 400, 3), (0.85, 0.75, 0.20), np.float32)
    for x0 in (150, 210):
        product[60:340, x0:x0 + 30] = (0.55, 0.40, 0.10)
    scene = np.full((500, 500, 3), (0.80, 0.72, 0.22), np.float32)
    scene[100:400, 200:240] = (0.50, 0.38, 0.12)
    save(OUT / "X01_product.png", product)
    save(OUT / "X01_scene.png", scene)

    notes = {
        "X01": {
            "pairs": "40,40=90,90; 360,40=410,90; 360,360=410,410; 40,360=90,410",
            "part": "130,50; 260,50; 260,350; 130,350",
            "erase": "190,140; 260,140; 260,410; 190,410",
        }
    }
    (OUT / "fixture-notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")


if __name__ == "__main__":
    make_fixtures()
