#!/usr/bin/env python3
"""Portrait route: find faces, and take back a detail-upscaled portrait (SeedVR2 or similar).

AI portraits fail on skin in two ways: a crackled / cellular fake texture, or waxy "plastic" skin with no
pores. Painting pores onto the skin alone looks pasted, because hair, eyes and lips keep the AI look. What
works is a real-detail upscaler on the WHOLE image (SeedVR2, Apache-2.0: Higgsfield "upscale", ComfyUI,
or local). This module only does what the upscaler does not:

  * faces(rgb)              -> which images are portraits (YuNet face detector, 230 KB, MIT)
  * take_back(orig, up)     -> resize to the original size (optional), colour-match back to the original
                               (upscalers shift colour a little), comparison board with the face
"""

from pathlib import Path

import cv2
import numpy as np

YUNET = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
MIN_FACE_FRAC = 0.06      # face width / image width; smaller faces are not worth a skin pass


def faces(rgb, min_score=0.8):
    """[(x, y, w, h, score)] of human faces, largest first."""
    h, w = rgb.shape[:2]
    s = 1024 / max(h, w)
    small = cv2.resize((np.clip(rgb, 0, 1) * 255).astype(np.uint8), (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (small.shape[1], small.shape[0]), min_score)
    _, f = det.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
    out = []
    for row in (f if f is not None else []):
        x, y, bw, bh = (row[:4] / s).tolist()
        lm = row[4:14].reshape(5, 2) / s
        eye_d = float(np.hypot(*(lm[0] - lm[1])))
        if not 0.25 < eye_d / max(bw, 1) < 0.65:      # animals / false hits
            continue
        out.append((x, y, bw, bh, float(row[14])))
    return sorted(out, key=lambda t: -t[2] * t[3])


def portrait_info(rgb):
    fl = faces(rgb)
    w = rgb.shape[1]
    big = [f for f in fl if f[2] / w >= MIN_FACE_FRAC]
    return {"faces": len(fl), "portrait": bool(big),
            "face_box": [int(v) for v in big[0][:4]] if big else None}
