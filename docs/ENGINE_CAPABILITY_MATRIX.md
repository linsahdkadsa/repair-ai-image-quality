# P01 引擎能力矩阵

日期：2026-11-04。`verified` 只表示本阶段在固定上游和合成样本上真实执行过；不表示 M1/M2/M3 或真实业务效果通过。

| 模式 | CLI / 入口 | 角色与参数范围 | 模型/外部条件 | 原始制品 | 可展示指标 | 降级、跳过与状态 | P01 事实 |
|---|---|---|---|---|---|---|---|
| 基础纹理修复 | `scripts/repair.py IMAGE...`；底层 `gpt_demaze.py SOURCE OUTPUT` | `input`；`--strength 0..100`；可选 `--model`、`--force`、`--protect-mask` | `gpt_maze_unet.onnx` + OpenCV CPU；无云密钥 | 修复图、JSON、可选 compare | `maze_score`、覆盖率、凸起前后、边缘保持、秒数、`method` | 模型不可用时 `method=spectral`；无明显迷宫、相机 EXIF、非 GPT/大图按规则跳过 | D01、D02、D03、D04、fallback、selftest verified |
| 颜色校正 | `repair.py --source BASE EDIT...`；底层 `color_match.py SOURCE EDIT OUTPUT` | `source` + `edit`；`--color-strength 0..100`；可选 `--paste-back`、mask、`--force-color` | 本地 NumPy/OpenCV；需要 source 有足够真实未改动区域 | 校色图、JSON、compare、可选 mask | 未改动区域、ΔE00、Lab 偏移、对齐分数、模型选择、秒数 | 灰模/白模、构图差异、整体故意调色、可信区域不足时 no-op；`--force-color` 仅显式人工决策 | C01 color-match verified；C02/C03 skip verified |
| 多轮链式处理 | `repair.py --source BASE --chain V1 V2...` | `source` 为最初底图；编辑轮次按 argv 顺序；同一 `--source` 对照 | 本地颜色匹配；每轮输出 | 每轮修复图、`chain_report.json` | 每轮校正前后 ΔE00、a*、b* | 缺少 source 或对照区域不足时拒绝/跳过 | 帮助和源码核对；未用独立 P01 chain 样本实际执行，`pending` |
| 局部贴回 | `repair.py --source BASE EDIT --paste-back` | `source` + `edit`；编辑区域由结构差异推断 | 本地颜色匹配 | source frame 中的结果图、JSON、compare | edited area share、输出尺寸、未改动像素来源 | 对齐失败或可信区域不足时 no-op | P01_local verified |
| 批量 | `repair.py IMAGE...` | 多个 `input`，每个独立报告 | 同基础纹理修复 | 每张图及 JSON | 每张独立指标和耗时 | 单张跳过不阻塞其他输入；错误必须逐项报告 | B01 verified |
| 人工清洗增强 | `controller.py plan/run/auto`；`auto --provider manual` | `input` + 外部 `washed`；提示词由上游生成 | 需要 Nano Banana/Gemini/FAL 或人工网页操作；无密钥时只生成 hand-wash 目录 | plan、提示词、待洗目录、完成后报告 | provider、needs_repair、review、rewash | 未提供外部结果时不得假装完成；保持人工等待 | plan 和 no-key manual branch verified；外部洗图未验证 |
| 人工超分/人像 | `controller.py portrait ... --upscaled DIR`；`portrait.py` | `input` + 外部 `upscaled`；可选 `--keep-size` | YuNet ONNX；整图外部真实细节放大器（如 SeedVR2） | 校色结果、face 信息、compare、portrait report | face 数量/框、颜色 ΔE、输出尺寸 | 无 candidate 或无可用大脸时跳过；外部超分不在本地能力内 | YuNet 加载与无脸 selftest verified；完整人像流程 pending |
| 产品局部移植实验 | `part_transplant.py prep/finish` | `scene`、`product`、>=4 keypoint pairs、part polygon；finish 接受 candidates | 本地透视、融合和形状检查；candidate 需要外部图像模型生成 | `meta.json`、`transplant.jpg`、`blend_input.png`、guide、prompt、finish report | pair residual、形状一致度、局部最大位移、接受/拒绝 | candidate 位移/重绘被拒；无合格 candidate 不得成功 | X01 synthetic geometry verified；真实产品与人工审核 pending |

## 适配器硬边界

- 后端只传固定 argv，不接收浏览器提供的 shell 字符串、可执行文件路径或任意环境变量。
- `--wash-cmd` 的 `shell=True` 是上游开发接口，不是应用安全接口；P02/P04 应默认禁用或只允许服务端白名单。
- `engineUsed` 必须记录 `unet`、`spectral`、`curves+lut` 等实际值；不能把“命令退出 0”当成算法执行。
- 外部洗图、外部超分、模型发布权利不属于本矩阵的本地 verified 能力。