# P01 结果摘要

| 样本/流程 | 实际结果 | 证据 |
|---|---|---|
| D01 | ONNX `unet`；maze score 0.9595；凸起 33.51 -> 1.77；edge 0.9874 | `results/D01/D01_mazey_fixed.json` |
| D02 | `no-op`；maze score 0；干净图保护 | `results/D02/D02_clean_fixed.json` |
| D03 | `no-op`；相机 EXIF 保护门命中 | `results/D03/D03_large_exif_fixed.json` |
| D04 | `no-op`；未检测到明显 GPT 迷宫特征 | `results/D04/D04_scaled_texture_fixed.json` |
| C01 | `color-match`；ΔE00 4.511 -> 0.055 | `results/C01/report.json` |
| C02 | `no-op`；灰模无可信对照区域 | `results/C02/report.json` |
| C03 | `no-op`；故意整体调色超出正常偏色范围 | `results/C03/report.json` |
| P01 | color-match + paste-back；edited area 31.41% | `results/P01/P01_local_edit_fixed.json` |
| B01 | 一张 demaze、一张 skip | `results/B01/*.json` |
| controller plan | 1/2 需要洗图；无密钥 manual 目录生成 | `results/controller-plan/plan.json`, `results/controller-manual/washed/` |
| fallback | 缺失 ONNX 时 `method=spectral` | `results/fallback/report.json` |
| X01 | good candidate 接受；moved candidate 拒绝 | `results/X01/finish_report.json` |

样本由 `docs/evidence/P01/generate_fixtures.py` 生成，清单与 SHA-256 见 `docs/fixtures/manifest.yaml`。