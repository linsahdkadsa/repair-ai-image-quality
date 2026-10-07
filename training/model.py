"""The maze filter network (shipped as scripts/models/gpt_maze_unet.onnx).

A small luminance U-Net (two down/up levels, width 24, ~470k parameters) that
predicts the maze component and subtracts it from its input (residual output).
Upsampling is bilinear x2 followed by a 3x3 conv rather than a transposed conv,
which is the usual cause of period-2/4 checkerboard artefacts.

Input and output: N x 1 x H x W luminance in 0..1, H and W multiples of 4.
"""
import torch
import torch.nn as nn


def block(ci, co):
    return nn.Sequential(nn.Conv2d(ci, co, 3, padding=1), nn.ReLU(inplace=True),
                         nn.Conv2d(co, co, 3, padding=1), nn.ReLU(inplace=True))


class MazeUNet(nn.Module):
    def __init__(self, w=24):
        super().__init__()
        self.e1, self.e2, self.e3 = block(1, w), block(w, 2 * w), block(2 * w, 4 * w)
        self.d1, self.d2 = nn.Conv2d(w, w, 2, stride=2), nn.Conv2d(2 * w, 2 * w, 2, stride=2)
        self.mid = block(4 * w, 4 * w)
        self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False)
        self.u2, self.c2 = nn.Conv2d(4 * w, 2 * w, 3, padding=1), block(4 * w, 2 * w)
        self.u1, self.c1 = nn.Conv2d(2 * w, w, 3, padding=1), block(2 * w, w)
        self.out = nn.Conv2d(w, 1, 3, padding=1)

    def forward(self, x):
        a = self.e1(x)
        b = self.e2(self.d1(a))
        c = self.mid(self.e3(self.d2(b)))
        y = self.c2(torch.cat([self.u2(self.up(c)), b], 1))
        y = self.c1(torch.cat([self.u1(self.up(y)), a], 1))
        return x - self.out(y)
