"""Shared image I/O, colour maths and comparison boards."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = None


# ---------------------------------------------------------------- I/O

def load_image(path, max_side=None):
    """Return (float32 RGB 0..1, info dict). Honours EXIF orientation."""
    image = Image.open(path)
    info = {
        "format": image.format,
        "icc_profile": image.info.get("icc_profile"),
        "size": image.size,
        "mode": image.mode,
    }
    try:
        exif = image.getexif()
        make = str(exif.get(271, "") or "").strip()
        model = str(exif.get(272, "") or "").strip()
        info["camera"] = " ".join(x for x in (make, model) if x) or None
    except Exception:
        info["camera"] = None
    if max_side and image.format == "JPEG":
        image.draft("RGB", (max_side, max_side))
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        info["alpha"] = np.asarray(rgba, dtype=np.uint8)[:, :, 3]
        image = rgba.convert("RGB")
    else:
        image = image.convert("RGB")
    if max_side and max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        info["alpha"] = None
    return np.asarray(image, dtype=np.float32) / 255.0, info


def save_image(path, rgb, info=None, quality=95):
    """Save float RGB 0..1, keeping the source ICC profile and alpha when present."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    u8 = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
    image = Image.fromarray(u8, "RGB")
    alpha = (info or {}).get("alpha")
    suffix = path.suffix.lower()
    if alpha is not None and alpha.shape == u8.shape[:2] and suffix in (".png", ".webp", ".tif", ".tiff"):
        image = Image.fromarray(np.dstack([u8, alpha]), "RGBA")
    kwargs = {}
    icc = (info or {}).get("icc_profile")
    if icc:
        kwargs["icc_profile"] = icc
    if suffix in (".jpg", ".jpeg"):
        kwargs.update(quality=quality, subsampling=0, optimize=True)
    elif suffix == ".webp":
        kwargs.update(quality=quality, method=6)
    elif suffix == ".png":
        kwargs.update(optimize=False, compress_level=6)
    image.save(path, **kwargs)
    return path


# ---------------------------------------------------------------- colour

def luma(rgb):
    # Explicit weighted sum: avoids float32 matmul FPE noise on some BLAS builds.
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((np.maximum(c, 0) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.maximum(c, 0) ** (1 / 2.4) - 0.055).astype(np.float32)


_M = np.array(
    [[0.4124564, 0.3575761, 0.1804375],
     [0.2126729, 0.7151522, 0.0721750],
     [0.0193339, 0.1191920, 0.9503041]],
    dtype=np.float64,
)
_M_INV = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)


def _mat(rgb, m):
    return (rgb[..., 0:1] * m[:, 0] + rgb[..., 1:2] * m[:, 1] + rgb[..., 2:3] * m[:, 2]).astype(np.float32)


def rgb_to_lab(rgb):
    xyz = _mat(srgb_to_linear(rgb), _M / _WHITE[:, None])
    eps = 216 / 24389
    f = np.where(xyz > eps, np.cbrt(np.maximum(xyz, 0)), (24389 / 27 * xyz + 16) / 116)
    lab = np.empty_like(xyz)
    lab[..., 0] = 116 * f[..., 1] - 16
    lab[..., 1] = 500 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200 * (f[..., 1] - f[..., 2])
    return lab


def lab_to_rgb(lab):
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    eps = 6 / 29
    xyz = np.where(f > eps, f ** 3, (f - 16 / 116) * 3 * eps * eps)
    xyz = xyz * _WHITE.astype(np.float32)
    return np.clip(linear_to_srgb(_mat(xyz, _M_INV)), 0.0, 1.0)


def delta_e2000(lab1, lab2):
    """Vectorised CIEDE2000 colour difference."""
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.mod(np.degrees(np.arctan2(b1, a1p)), 360)
    h2p = np.mod(np.degrees(np.arctan2(b2, a2p)), 360)
    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh) / 2)
    Lpm = (L1 + L2) / 2
    Cpm = (C1p + C2p) / 2
    hsum = h1p + h2p
    hpm = np.where(
        C1p * C2p == 0,
        hsum,
        np.where(np.abs(h1p - h2p) <= 180, hsum / 2, np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2)),
    )
    T = (1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm))
         + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63)))
    dtheta = 30 * np.exp(-(((hpm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc = 1 + 0.045 * Cpm
    Sh = 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


# ---------------------------------------------------------------- boards

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def font(size):
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def to_pil(rgb):
    return Image.fromarray(np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8), "RGB")


def _fit(image, size, resample=Image.Resampling.LANCZOS):
    copy = image.copy()
    copy.thumbnail(size, resample)
    canvas = Image.new("RGB", size, (24, 26, 30))
    canvas.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
    return canvas


def comparison_board(path, title, subtitle, panels, crops=(), crop_zoom=2):
    """panels: list of (label, PIL image) shown full; crops: list of (x0,y0,x1,y1) boxes
    in the coordinate frame of the LAST panel image, rendered for every panel."""
    n = len(panels)
    width = 1680
    margin, gap = 36, 18
    panel_w = (width - 2 * margin - (n - 1) * gap) // n
    ref = panels[-1][1]
    panel_h = int(min(620, panel_w * ref.height / ref.width))
    crop_h = panel_w
    height = 130 + panel_h + 50 + len(crops) * (crop_h + 50) + 30
    board = Image.new("RGB", (width, height), (14, 16, 20))
    draw = ImageDraw.Draw(board)
    draw.text((margin, 24), title, font=font(36), fill=(240, 242, 246))
    draw.text((margin, 76), subtitle, font=font(20), fill=(120, 214, 170))
    top = 130
    for i, (label, image) in enumerate(panels):
        x = margin + i * (panel_w + gap)
        board.paste(_fit(image, (panel_w, panel_h)), (x, top))
        draw.text((x + 10, top + 8), label, font=font(24), fill=(255, 206, 92), stroke_width=3, stroke_fill=(0, 0, 0))
    y = top + panel_h + 50
    for box in crops:
        for i, (label, image) in enumerate(panels):
            x = margin + i * (panel_w + gap)
            sx = image.width / ref.width
            sy = image.height / ref.height
            b = (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))
            crop = image.crop(b)
            crop = crop.resize((crop.width * crop_zoom, crop.height * crop_zoom), Image.Resampling.NEAREST)
            board.paste(_fit(crop, (panel_w, crop_h), Image.Resampling.NEAREST), (x, y))
            draw.text((x + 10, y + 8), f"{label} · {crop_zoom * 100}% 局部", font=font(20), fill=(255, 206, 92),
                      stroke_width=3, stroke_fill=(0, 0, 0))
        y += crop_h + 50
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    board.save(path)
    return path
