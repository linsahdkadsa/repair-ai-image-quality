# Repair AI Image Quality

一个面向 Codex 的一键式 AI 图片去噪 Skill：用户只需要控制去噪强度，后台自动识别噪点类型、选择安全路线、降低过强候选或直接跳过处理。

核心原则：**必须同时满足“噪点得到可见清理”和“原图外观保持稳定”，否则返回原图。**

## 能做什么

- 清理亮度噪点、彩色噪点、压缩颗粒、脏渐变和暗部色块。
- 一个 `0–100` 强度控制器，默认值为 `60`。
- 后台自动比较 guided、colored NLM、亮度/色度分离 NLM 等确定性候选。
- 自动保护人脸、手部、文字、轮廓、光源、细线、纹样和材质细节。
- 候选过强时自动降档；图片已经干净时自动 `no-op`。
- 输出处理图、JSON 报告以及原图/结果对比图。
- 支持保护蒙版：白色区域保持逐像素一致。

本项目不进行生成式重绘，也不修复破碎、融合、重复或不连贯的物体结构。

## 安装为 Codex Skill

```powershell
git clone https://github.com/linsahdkadsa/repair-ai-image-quality.git "$HOME/.codex/skills/repair-ai-image-quality"
```

Windows 首次使用时创建独立运行环境：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$HOME/.codex/skills/repair-ai-image-quality/scripts/setup_runtime.ps1" -Python (Get-Command python).Source
```

依赖包括 Python 3、NumPy、Pillow 与 OpenCV。运行环境不会提交到仓库。

## 一键运行

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_one_click.ps1 `
  SOURCE.png OUTPUT.png `
  --strength 60 `
  --detail-mode auto `
  --content-risk high `
  --report REPORT.json `
  --comparison COMPARISON.png
```

常用强度建议：

- `0`：保持原图不变。
- `1–35`：保守去噪。
- `36–70`：自适应去噪，推荐默认 `60`。
- `71–100`：提高候选清理上限，但安全门仍可能自动降档。

如果不需要特殊保护，可省略 `--content-risk high`。遇到暗背景上的电线、星点、发光线路或细丝时，可使用 `--content-risk sparse-lines`。

## 独立保真检查

```powershell
python .\scripts\check_fidelity.py SOURCE.png OUTPUT.png --preset strong-denoise --json
```

指标只作为安全门，不等同于主观画质证明。最终仍应检查全图和代表性的 100% 局部。

## 设计边界

- 不改变构图、裁切、相机、人物身份、姿态、物体数量或灯光方向。
- 不使用白膜转换、生成式补画、结构重建或全局重风格化。
- 不承诺“无损”或“适用于每一张图片”。
- 对无法安全清理的区域，保持原样是一种正确结果。

完整路由与安全规则见 [SKILL.md](SKILL.md) 和 [routing-and-guardrails.md](references/routing-and-guardrails.md)。

## License

[MIT](LICENSE)
