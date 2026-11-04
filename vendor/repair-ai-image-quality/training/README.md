# Retraining the maze filter

The skill ships a trained model (`scripts/models/gpt_maze_unet.onnx`) and only
needs numpy, Pillow and OpenCV to run it. This folder is for when a new GPT
image version draws a different maze, or you want to train on your own renders.
It needs PyTorch ≥ 2.5 (`pip install torch onnx`) on top of `scripts/requirements.txt`.

```bash
cd training
# 1. patches: GPT renders that show the maze + clean images (photos, other models)
python harvest.py --gpt ~/renders/gpt --clean ~/photos ~/banana --out data --hold eval_
# 2. train (~1 h on an Apple M-series GPU, 30k steps; also CUDA / CPU)
python train.py --data data --out maze_unet.pt
# 3. export to the file the skill loads (checks PyTorch vs OpenCV output)
python export.py maze_unet.pt ../scripts/models/gpt_maze_unet.onnx
# 4. regression test
../scripts/run.sh selftest
```

What matters, learned the hard way:

- **Harvest the maze, don't model it.** The real maze is not Gaussian and not
  stationary: amplitude follows brightness, cell size varies across a surface.
  A synthetic ring-spectrum noise alone trains a filter that misses half of it.
  `harvest.py` band-passes confident maze tiles of real renders and stores them
  normalised by brightness; training adds them to clean patches. 30 % synthetic
  ring noise is mixed in so the network does not memorise the harvested fields.
- **Teach it what to keep.** 25 % of samples have no maze, and `texture.npy`
  holds clean patches with real texture in the maze band (skin, hair, knit,
  fleece, foliage). Without them the network smooths skin and knit.
- **No transposed convolutions.** Upsampling is bilinear + 3×3 conv.
- **Native scale only.** Train and run at the resolution GPT renders at (≤ 2048 px).
  A render upscaled 2× has a maze twice as large; the detector skips it.
- **Validate on held-out renders.** Keep the evaluation images out of
  `harvest.py` with `--hold`, and give `train.py` a fixed validation set
  (`--val-clean/--val-noisy`): real maze from the held-out renders added to
  clean crops, so PSNR against the clean crop is measurable.

Data provenance: the shipped model was trained on patches from the
maintainer's own GPT Image 2.5 renders and image library. No public research
datasets were used (several common ones, e.g. DIV2K, are licensed for research
only).
