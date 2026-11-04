# P01 上游与本地运行基线

日期：2026-11-04
阶段：P01
状态：算法入口与本地 CPU 基线已复验；模型发布权利待确认

## 固定来源

- 仓库：`linsahdkadsa/repair-ai-image-quality`
- 来源地址：`https://github.com/linsahdkadsa/repair-ai-image-quality`
- 固定提交：`49170b9f98be4541fb46c9d0fdc97a0c5078d8e0`
- 提交信息：`controller auto: the skill calls Nano Banana itself...`
- 提交时间：`2026-10-12T11:36:38+08:00`
- tree SHA：`6bc9916f817c53f81602427b625927011607ff8b`
- API zipball SHA-256：`9835AB58F8E7F57DD52B08568795D610439D851CCCCB4D4417A204132F9A95F1`
- 固定副本：`vendor/repair-ai-image-quality/`
- 来源与下载记录：`docs/evidence/P01/upstream-source.txt`
- 固定副本不含嵌套 `.git`；没有执行上游安装脚本后再做来源检查。

根代码带 MIT `LICENSE`。这只覆盖明确处于该许可证范围内的代码；不能自动覆盖模型权重、训练数据和外部服务。

## 模型与依赖

| 文件 | 大小 | SHA-256 | 当前许可结论 |
|---|---:|---|---|
| `scripts/models/gpt_maze_unet.onnx` | 1,881,630 bytes | `C8C9515C2D7E18E4D08E7B867E92BFFF75AB357AAAA6DFBB48920D685DCA5F09` | `training/README.md` 只声明由维护者自有 GPT Image 2.5 渲染和图像库训练；未提供独立权重/训练数据发布许可，待确认 |
| `scripts/models/face_detection_yunet_2023mar.onnx` | 232,589 bytes | `8F2383E4DD3CFBB4553EA8718107FC0423210DC964F9F4280604804ED2552FA4` | 网络恢复后已与 OpenCV Zoo 对应 media 资产逐字节匹配；目录提供 MIT 许可证，保留该许可证即可继续评估 |

本机环境：Windows 11 x64，Intel Core i5-1135G7，15.71 GiB RAM，Python 3.12.10，NumPy 2.5.3，Pillow 12.3.0，OpenCV 4.13.0。上游声明的 Python 3.9+ 与本机组合可运行；尚未证明目标 Windows 设备兼容性。

运行不需要云密钥或 GPU。`scripts/requirements.txt` 仅声明 NumPy、Pillow、OpenCV 范围；本阶段没有创建项目锁文件，也没有安装 npm 项目。

## 真实执行结果

- `pwsh scripts/run.ps1 selftest`：18/18 PASS，实际加载 `gpt_maze_unet.onnx`，同时覆盖谱域降级；完整输出见 `docs/evidence/P01/run-logs/selftest-pwsh.txt`。
- Windows PowerShell 5.1 按计划命令解析无 BOM UTF-8 的 `run.ps1` 失败；原始错误见 `docs/evidence/P01/run-logs/selftest.txt`。使用 PowerShell 7 `pwsh` 成功，不把 5.1 失败伪装成算法失败。
- 各入口帮助均已执行并保存：`docs/evidence/P01/run-logs/*-help.txt`。
- D01 使用真实 ONNX 学习模型：迷宫覆盖 96%，频谱凸起 `33.51 -> 1.77`，边缘保持 `0.9874`。
- 缺失模型路径的定点试验明确使用 `spectral` 降级，报告见 `docs/evidence/P01/results/fallback/report.json`。
- D03 默认识别合成相机 EXIF 并跳过；D04 默认未检测到明显 GPT 迷宫特征并跳过。只有显式 `--model gpt-image-2` 或 `--force` 才绕过相机/大图保护门。
- C01 校色：未改动区域 `0.7726`，ΔE00 均值 `4.511 -> 0.055`。
- C02 灰模：未改动可对照区域为 `0%`，明确跳过。
- C03 故意整体调色：明确按超出正常 banana 偏色范围跳过。
- P01 回贴：编辑区域占 `31.41%`，其余像素来自 source frame。
- B01：一张真实执行、一张干净图跳过，均生成 JSON 报告。
- controller：生成 plan；无密钥 `auto --provider manual` 生成手动洗图目录，不宣称外部洗图已完成。
- X01：`prep` 生成透视移植制品；原位 candidate 接受，横向移动 10 px candidate 拒绝。

结果文件、报告和原始命令索引见 `docs/evidence/P01/commands.txt` 与 `docs/evidence/P01/results-summary.md`。

## 入口与边界

上游 `wash.py` 的 `--wash-cmd` 最终调用 `subprocess.run(..., shell=True)`。应用适配器不得把浏览器输入或任意客户端字符串传给该参数；默认应禁用任意 shell，采用固定 argv、固定 provider 和白名单配置。`run.ps1` 仅用于开发/验证包装，发布运行时不得在线 bootstrap 或按需联网安装依赖。

本阶段不把上游 `controller auto` 的云 API、SeedVR2、Nano Banana 或人工洗图结果计为本地能力；它们都需要外部模型、用户操作或真实凭据。

## 未完成与交接限制

1. GPT 迷宫模型的权重与训练数据单独许可/来源没有得到权利人确认，不能携带该模型直接发布；YuNet 已有对应来源和 MIT 许可证证据，但发布时仍须保留上游许可声明。
2. 样本全部为 P01 生成的合成样本，不代表真实业务图片、真实用户效果或人工盲审结果。
3. 没有运行 `npm install` 或 `npm test`：仓库当前没有 `package.json`，该检查对 P01 不适用。
4. 没有目标 Windows 设备、真实身份、部署服务或浏览器端到端证据；M1/M2/M3 均未通过。
5. 本机样本耗时是实验室开发机事实，不是性能承诺；正式像素桶、冷启动和目标机测量留给 P05/P12。

网络恢复后的复核记录见 `docs/evidence/P01/model-rights-recheck-20261104.txt`。该复核解除的是 YuNet 的来源/许可证证据缺口；GPT 迷宫模型的独立权重/训练数据再发布授权仍未确认，因此整体模型发布门禁仍保持阻断。
