#!/usr/bin/env python3
"""Export a trained checkpoint to the ONNX file the skill loads, and check it.

    python export.py maze_unet.pt ../scripts/models/gpt_maze_unet.onnx

ONNX opset 13 with dynamic height/width, run by OpenCV's DNN module (no extra
runtime dependency). The check runs the same input through PyTorch and OpenCV;
the difference should be ~1e-4 grey levels.
"""
import argparse

import numpy as np
import torch

from model import MazeUNet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("onnx")
    ap.add_argument("--width", type=int, default=24)
    a = ap.parse_args()
    m = MazeUNet(a.width)
    m.load_state_dict(torch.load(a.checkpoint, map_location="cpu"))
    m.eval()
    torch.onnx.export(m, torch.zeros(1, 1, 256, 256), a.onnx, input_names=["y"], output_names=["out"], opset_version=13,
                      dynamic_axes={"y": {2: "h", 3: "w"}, "out": {2: "h", 3: "w"}}, dynamo=False)
    import cv2
    x = np.random.RandomState(0).rand(1, 1, 200, 312).astype(np.float32)
    net = cv2.dnn.readNetFromONNX(a.onnx)
    net.setInput(x)
    with torch.no_grad():
        ref = m(torch.from_numpy(x)).numpy()
    diff = float(np.abs(net.forward() - ref).max() * 255)
    print(f"exported {a.onnx}; PyTorch vs OpenCV {cv2.__version__}: max difference {diff:.5f} grey levels")
    if diff > 0.05:
        raise SystemExit("OpenCV output differs from PyTorch - do not ship this file")


if __name__ == "__main__":
    main()
