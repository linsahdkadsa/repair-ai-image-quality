# Repair AI Image 分阶段实施计划 / Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 仅在人类明确授权并行代理后使用 superpowers:subagent-driven-development。

**Goal:** 建成交付可复验的本地图像修复能力测试平台，并让每阶段的实物产出成为下一阶段的明确输入。

**Architecture:** 前后端分离的模块化单体。FastAPI 按 api → service → repo → core 分层，infra 承担进程、认证、日志和上游适配，通过 core 中的接口注入；阻塞图像处理使用受限子进程。前端采用唯一组件体系和单一服务端缓存，后端持久化任务、文件、权限及评估口径。

**Tech Stack:** Python/FastAPI/Pydantic/pytest；Vite/React/TypeScript strict/Ant Design/ProComponents/React Router Data Mode/SWR/Axios/CSS Modules/ECharts/Day.js；Storybook/Vitest/RTL/Playwright/OpenAPI。

---

## 1. 执行边界与基线

- 本文编制日期：2026-11-04，同日更新标准引用。首次编制前项目目录为空；当前文档基线包含本文及 docs/standards/ 下两份标准副本，尚无业务工程与 Git 仓库，所有后续源文件均为计划创建项。
- 本次仅复制两份标准并修改计划文档。文中安装、测试、克隆、启动、构建、部署和提交命令均供后续阶段执行，目前未执行；本次文档操作不代表 P00 或任何实施阶段已完成。
- 两份用户指定标准的项目内副本为本项目 L0 约束，优先于本文的实现建议，后续阶段统一读取以下本地文件：
  - `G:/project/RepairAiImage/docs/standards/通用架构设定.md`
  - `G:/project/RepairAiImage/docs/standards/通用前端设定.md`
- 执行阶段读取上述项目内副本，并按第 1.1 节核对 SHA-256；项目的架构映射写入自己的架构文档。标准副本的后续调整须先做影响分析并更新版本与哈希记录。
- 不创建、修改或删除 `G:/project/RepairAiImage/migrations/`。首版使用持久化本地文件仓储，不引入数据库迁移。
- 不在源码、配置模板、前端包、测试快照、日志或交接证据中写入密钥。前端函数组件，中文注释；提交遵循 Conventional Commits。
- 项目统一入口：根目录 `npm install`、`npm run dev`、`npm test`；开发前端固定 3000，后端默认 8000。Python 依赖安装是首次环境准备的独立步骤，不能由启动脚本隐式联网完成。
- `npm test` 聚合后端、前端及契约测试；交付前另跑静态检查、构建、E2E、视觉与部署检查。没有通过全部适用门禁，不提 PR。
- 不为没有业务依据的场景引入微服务、BFF、Redis、微前端、第二套 UI/状态管理库或万能组件。
- 命名冲突处理建议：架构标准第 3 节要求组件文件 PascalCase，前端标准“编码规范”条款要求文件名统一英文 kebab-case。本文按前端专项规则规划前端文件名为 kebab-case，组件导出标识符为 PascalCase；P00 将原文条款、该取舍和影响记录进 ADR 后冻结。后端 Python 文件按 snake_case。此项是本计划的冲突处理建议，不将其描述成两份原文完全一致。

### 1.1 标准副本来源与版本基线

复制日期：2026-11-04。两份文件按原始字节复制，编码、换行与正文保持一致；本项目以 `docs/standards/` 内的副本为执行依据。

| 项目内标准 | 原始来源（仅用于追溯） | 字节数 | SHA-256 |
| --- | --- | --- | --- |
| `docs/standards/通用架构设定.md` | `G:/doubaoAI/Hybrid Platform Base/docs/standards/通用架构设定.md` | 8376 | `F32DA7BBBEF8B6369A7C6839A4411AF3553FE35E72C81775FF288294BB631C6F` |
| `docs/standards/通用前端设定.md` | `G:/doubaoAI/Hybrid Platform Base/docs/standards/通用前端设定.md` | 28034 | `BDCBCC26FE6F7E482E7C27A7111DFD1D73CBD3D20D6708462B8FDF67D9CA73E2` |
原始来源目录仅用于追溯，不作为构建、测试、部署或后续阶段的读取依赖。本次未修改来源文件；来源项目今后的修改不会自动同步至本项目。

如需采纳来源标准的新版本，先审查条款差异及对架构、前端、契约和验收的影响，再更新项目副本、本文中的复制日期/来源版本/哈希及相关 ADR，并重新验收受影响阶段。当前版本以复制日期和 SHA-256 标识；不自动覆盖标准副本。

## 2. 能力边界与交付级别

平台定位为“修复算法验证与结果比较工具”。基础能力围绕 GPT 迷宫纹/网格噪声、Banana 偏色、多轮修图校色和贴回；不对通用老照片修复、任意去模糊或细节重建作效果承诺。

上游信息来自前一阶段调研，执行前在 P01 重新核对。曾观察到的提交候选为 `49170b9f98be4541fb46c9d0fdc97a0c5078d8e0`，仅为待复核的候选，不声称它仍是最新提交。不直接跟随主分支升级。

- **M1：P06 完成。** 用户通过真实身份上传图片、执行真实基础修复、查看进度与比较、下载结果；系统记录模型执行或降级情况。
- **M2：P09 完成。** 在 M1 上具备颜色/链式/贴回、完整任务管理、系统状态、批量评估和可复验报告，构成核心产品验收范围。
- **M3：P12 完成。** P10 的手动增强流程可用，P11 的实验移植流程按实际能力验收，完成 Windows 本地部署与离线包验证。云服务或额外模型若缺条件，明确显示未启用；相关能力不能标记“已通过真实验收”。

本地部署路径：基础处理拟采用随上游交付的 ONNX/OpenCV CPU 推理，优先验证 Windows 本机独立运行。基础能力不以 GPU、云密钥或 SeedVR2 为前提。云清洗、额外超分模型、实验移植分别验收，不把它们的限制归到所有基础能力。目标机能否达到可接受速度，以 P01 基准与 P12 目标机实测为准。

## 3. 阶段链路与交接制度

```text
P00 需求/标准冻结 → P01 上游/样本基线 → P02 工程/CI
 → P03 配置/身份/文件 → P04 任务执行内核 → P05 前端公共基础
 → P06 基础修复闭环 → P07 颜色/链式/贴回 → P08 任务中心/系统
 → P09 批量评估 → P10 手动增强/外部适配 → P11 实验移植
 → P12 打包/目标部署/验收
```

每个阶段都有唯一交接入口 `G:/project/RepairAiImage/docs/handoffs/PXX.md`，与同名 JSON 清单。后者是非敏感产物索引，不是凭据或业务配置。下一阶段读取前一阶段入口，沿 `previousHandoff` 获取更早阶段产物；不得用聊天记录替代契约文件。

交接清单固定字段：

```json
{
  "phase": "P00",
  "status": "accepted",
  "previousHandoff": null,
  "sourceRevision": "documentation-baseline",
  "standardHashes": {"architecture": "recorded-by-script", "frontend": "recorded-by-script"},
  "outputs": [{"path": "docs/SPEC.md", "sha256": "recorded-by-script"}],
  "verification": [{"command": "npm run check:handoff -- P00", "exitCode": 0, "report": "docs/evidence/P00/handoff-check.txt"}],
  "capabilities": {"demaze": "unverified"},
  "limitations": [],
  "nextPhase": "P01"
}
```

上例展示字段结构；执行时哈希和报告由脚本从实际文件生成，禁止照抄示例值。P00/P01 在脚本建立前使用 `Get-FileHash` 和人工检查，P02 补录校验，不伪造尚不存在的命令运行记录。

交接规则：

1. 每阶段先检查输入是否齐全、版本/哈希一致、上阶段状态为 accepted。
2. 任务清单执行完成、适用检查通过、证据存在后，才写 accepted；失败时写 failed、失败原因和可复跑命令。
3. 外部能力缺条件可以记录 disabled 或 unavailable，并说明原因；不能把失败的必需能力改为可选来通过门禁。
4. 关键契约变更先更新契约与受影响测试；使旧交接失效，重跑受影响阶段，不要求无差别重跑全部阶段。
5. 阶段证据存放于 `G:/project/RepairAiImage/docs/evidence/PXX/`；真实图片、运行状态、密钥和可识别个人资料不进 Git。可提交的脱敏测试报告与敏感原始证据分开存放，记录访问位置。
6. `check:handoff` 拒绝缺失产物、哈希不一致、必测项失败、下游引用不存在和必需能力未通过。不能仅检查 JSON 格式。

## 4. 文件责任与工程命令

所有文件以 `G:/project/RepairAiImage/` 为工程根。以下精确路径确定首版边界，允许按单一职责增加同目录小文件，不允许绕过层次。

| 路径 | 责任 |
| --- | --- |
| `G:/project/RepairAiImage/package.json` | 工作区、统一开发/测试/构建/质量门禁入口 |
| `G:/project/RepairAiImage/tools/check-handoff.mjs` | 校验阶段清单、证据与产物哈希 |
| `G:/project/RepairAiImage/tools/check-boundaries.mjs` | 静态检查前后端依赖方向与禁止项 |
| `G:/project/RepairAiImage/tools/export-openapi.py` | 从应用导出稳定排序的 OpenAPI |
| `G:/project/RepairAiImage/backend/pyproject.toml`、`G:/project/RepairAiImage/backend/requirements.lock` | Python 包与可复现依赖锁定 |
| `G:/project/RepairAiImage/backend/src/core/config.py`、`models.py`、`errors.py`、`ports.py` | 配置、领域类型、错误码、仓储/执行器协议 |
| `G:/project/RepairAiImage/backend/src/repo/task_repository.py`、`artifact_repository.py`、`evaluation_repository.py` | 原子文件读写与索引，不包含业务判定 |
| `G:/project/RepairAiImage/backend/src/service/task_service.py`、`repair_service.py`、`evaluation_service.py` | 状态规则、模式编排、评估口径 |
| `G:/project/RepairAiImage/backend/src/infra/repair_engine_adapter.py`、`process_runner.py`、`provider_adapter.py` | 上游参数映射、进程树、外部模型适配 |
| `G:/project/RepairAiImage/backend/src/infra/auth.py`、`logging.py`、`trace.py` | 身份/权限、脱敏日志、链路传递 |
| `G:/project/RepairAiImage/backend/src/api/app.py`、`dependencies.py`、`dto.py`、`routes/` | 组合根、依赖注入、外部契约与薄路由 |
| `G:/project/RepairAiImage/backend/tests/` | API、真实进程、重启恢复、制品权限等集成测试 |
| `G:/project/RepairAiImage/frontend/src/app/`、`layouts/` | 应用提供器、路由、错误边界、ProLayout |
| `G:/project/RepairAiImage/frontend/src/design-system/` | Token、Ant/ECharts 主题、列表/详情/工作台/分析模板 |
| `G:/project/RepairAiImage/frontend/src/shared/` | HTTP、身份、SSE、通用组件与纯工具；不引用业务模块 |
| `G:/project/RepairAiImage/frontend/src/generated/api-types.ts` | OpenAPI 自动生成类型，禁止手工修改 |
| `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/` | 模式、上传、参数、执行、比较、人工输入/移植面板 |
| `G:/project/RepairAiImage/frontend/src/modules/tasks/`、`evaluation/`、`system/` | 对应业务页面，每模块含 api.ts、queries.ts、types.ts、index.ts |
| `G:/project/RepairAiImage/frontend/.storybook/`、`frontend/tests/e2e/` | 共享组件目录、交互/端到端/视觉基线 |
| `G:/project/RepairAiImage/vendor/repair-ai-image-quality/` | P01 获取的固定上游，不混入应用状态或直接改算法 |
| `G:/project/RepairAiImage/deploy/` | 安装、启动、离线构建、升级、回滚与配置模板 |
| `G:/project/RepairAiImage/docs/` | SPEC、架构、契约、测试、部署、阶段交接与证据索引 |

Python 单元测试与被测模块同目录，如 `G:/project/RepairAiImage/backend/src/service/test_task_service.py`；跨层测试在 backend/tests，避免重复测试同一实现。

P02 必须提供的根脚本契约：

| 命令，工作目录均为工程根 | 确定行为 |
| --- | --- |
| `npm install` | 安装工作区 Node 依赖；生成并提交 package-lock.json |
| `npm ci` | CI 严格按锁文件安装，不更新锁文件 |
| `npm run dev` | 并行启动前端 3000/后端 8000；缺 Python 环境直接报准备命令，不隐式安装 |
| `npm test` | 执行 pytest 全部单元/集成测试、Vitest/RTL 与契约检查；任一失败返回非零 |
| `npm run test:backend -- <pytest参数>` | 使用 .venv Python 转发 pytest 参数，Windows 不依赖激活脚本 |
| `npm run test:frontend -- <Vitest参数>` | 转发参数给前端 Vitest，默认非 watch |
| `npm run check` | 类型、ESLint、Stylelint、格式、Python 静态检查、分层、契约、依赖治理；警告失败 |
| `npm run api:generate`、`npm run api:check` | 导出/生成类型；检查已提交生成物是否同步 |
| `npm run build`、`npm run build:storybook` | 构建应用和 Storybook |
| `npm run test:e2e`、`npm run test:visual` | 真实本地 API 的关键业务 E2E、固定环境视觉回归 |
| `npm run check:handoff -- P06` | 检查指定阶段真实交接清单 |
| `npm run verify` | check → test → 两项构建 → E2E → 视觉；部署验收在 P12 单独执行 |

根启动器用 Node spawn 的参数数组，不拼接 shell 命令；Ctrl+C 关闭所启动的前后端子进程。VS/PowerShell 不要求另装 pnpm；标准涉及包管理器版本一致性的条款映射为固定 Node/npm 版本。

## 5. 先冻结的业务与接口契约

### 5.1 身份、范围与存储

首版按单实例、命名用户实施；不引入完整多租户。默认本地认证使用受控账号的 HTTP Basic，浏览器原生认证挑战；密码只存经过审核的密码哈希，来源为受控凭据存储/环境变量，启动缺失即失败。P00 若已有企业 SSO，替换为其既有网关契约并记录 ADR；未完成真实身份验证不能以模拟用户验收。

- viewer：查看自己有权访问的任务、结果与报告；operator：在 viewer 上创建/取消/重试自己的任务和评估；admin：配置、诊断、日志与清理，访问他人任务须记录审计。
- 后端从已认证身份确定 ownerId，拒绝信任浏览器提交的 ownerId。P03 校验两账号隔离及 admin 审计。
- 所有应用页面、静态包、API、SSE、制品均鉴权；仅 healthz、readyz 与经批准的公开文档免鉴权。开发 Vite 只绑定 loopback，并通过 P05 的认证中间件保护页面、静态资源与开发连接；认证后端不可用时拒绝访问，不设置页面 shell 绕过鉴权的例外。
- Basic 在同源 SSE/下载中验证凭据传递；生产非 loopback 访问强制 HTTPS。写操作校验 Origin 与同源策略，无宽松跨域凭据配置。不使用 localStorage 保存令牌或业务数据。
- 受控凭据文件通过明确的管理员重载流程加载：先验证完整新版本，再原子替换内存快照；重载成功后下一次请求拒绝旧凭据，失败则保留旧版本并报告失败。仅从环境变量注入时，轮换需要受控重启，重启前不能声称旧凭据已撤销。首版不依赖进程环境变量自动刷新。测试分别覆盖两种生效时点、无凭据、错误凭据和越权；SSO 模式另外覆盖到期会话。
- 单实例独占 data 根目录锁；任务 JSON 使用 schemaVersion、version 乐观锁、临时文件+原子替换。数据位于应用安装目录之外的可配置 data 根，启动验证可写及可用空间。

### 5.2 状态与执行语义

任务状态仅使用：`queued / running / succeeded / failed / canceling / canceled`。

- queued → running/canceled；running → succeeded/failed/canceling；canceling → canceled，确认进程树终止后再进入 canceled。
- 终态不可重开。重试生成新 taskId 并记录 retryOf；状态版本冲突返回 409。
- 人工等待用 `running + stage=waiting_input + inputRequest` 表示，释放 worker，不新增含糊的生命周期状态；恢复使用显式 resume 命令。
- item 状态独立：pending/running/succeeded/skipped/failed/canceled。需人工审核是 `reviewRequired` 标志，不混成任务状态。
- 所有 item 完成且无失败时任务 succeeded，允许含 skipped；全部 skipped 时显示“未处理”，禁止当作修复成功计数。部分失败为 failed，保留已成功制品。
- 进度由阶段、已处理项数、总项数形成；未知时显示不定进度。固定阶段权重如确需使用，必须在契约说明，不用定时器制造百分比。
- 重启时 queued 保留排队，waiting_input 保留等待，原正在计算的 running/canceling 在确认无孤儿进程后记 failed/WORKER_INTERRUPTED。外部结果未知用 error_code=PROVIDER_RESULT_UNKNOWN，禁止自动重试或自动重复付费。
- SSE 使用递增 eventId 和持久化有限事件日志；先发送快照，再增量；Last-Event-ID 超出保留窗口时发 reset/snapshot。关闭流不取消任务，取消必须 POST。

### 5.3 HTTP 契约最小全集

所有 JSON 成功返回 `{"code":0,"msg":"ok","data":...}`；失败返回 `{"error_code":"UPPER_SNAKE_CASE","message":"安全消息","trace_id":"..."}`。文件下载和 SSE 保持各自内容类型，通过响应头和事件传 trace。

| 方法与路径 | 语义 |
| --- | --- |
| GET `/api/v1/session` | 当前用户、权限与认证方式，不返回凭据 |
| GET `/api/v1/capabilities` | 各模式 availability/reason、参数边界、模型/上游版本、是否降级 |
| POST `/api/v1/uploads` | 单文件 multipart；校验、私有存储，返回 uploadId/尺寸/哈希/过期时间 |
| DELETE `/api/v1/uploads/{uploadId}` | 删除自己尚未被任务引用的上传；引用冲突 409 |
| POST `/api/v1/tasks` | 模式、输入角色绑定、参数、Idempotency-Key；返回 202 与 taskId |
| GET `/api/v1/tasks`、GET `/api/v1/tasks/{taskId}` | 受权限约束的分页列表与详情 |
| POST `/api/v1/tasks/{taskId}/cancel`、`/retry` | 取消幂等；重试返回新任务，禁止隐式重复写 |
| POST `/api/v1/tasks/{taskId}/resume` | 上传人工输入后继续；inputRequestId+version，重复/过期提交受控 |
| GET `/api/v1/tasks/{taskId}/events` | 认证的同源 SSE，支持断线恢复与终态关闭 |
| GET `/api/v1/tasks/{taskId}/artifacts` | 制品元数据、角色、格式、大小与保留期限 |
| GET `/api/v1/tasks/{taskId}/artifacts/{artifactId}` | 权限校验后下载/预览，禁止传物理路径 |
| GET `/api/v1/tasks/{taskId}/logs?cursor=...` | 脱敏的分页诊断，管理员权限 |
| DELETE `/api/v1/tasks/{taskId}` | 终态任务清理；先检查引用，审计并清理私有文件 |
| POST `/api/v1/evaluations`、GET `/api/v1/evaluations/{evaluationId}` | 创建/查询评估记录，复用任务执行内核 |
| POST `/api/v1/evaluations/{evaluationId}/cancel` | 取消该评估及其尚未完成的子任务 |
| GET `/api/v1/evaluations/{evaluationId}/reports/{format}` | CSV/JSON 报告，format 枚举，鉴权/审计/大小限制 |
| GET `/api/v1/system/status` | 依赖、模型、存储和 provider 状态，脱敏 |
| GET `/healthz`、GET `/readyz` | 存活恒 200；必需依赖未就绪为 503，公开摘要不泄露路径/凭据 |

系统配置首版使用经过白名单约束的 YAML+环境变量；system 页面以只读诊断为主，不提供任意命令/密钥编辑器。任务删除若被评估引用返回 409；先清理评估再清理其任务。P09 增加管理员 DELETE `/api/v1/evaluations/{evaluationId}`，业务与审计规则同步写入 OpenAPI。

上传输入模型：`inputs: [{role, uploadId, sequence?}]`。role 为 input/source/edit/chain_step/mask/ground_truth/washed/upscaled/scene/product/keypoints/candidate。模式定义所允许的角色和数量；链式显式 sequence 排序，不能依赖文件名排序。上传文件先处于暂存区，任务创建时一次性校验归属并绑定，缺失/过期输入不入队。

错误与状态：400 无效模式/配对/图像；401 认证；403 权限；404 资源；409 状态/版本/引用/幂等冲突；413 文件过大；415 类型不支持；422 字段校验；429 带 Retry-After；503 必需依赖缺失；500 对外仅安全消息与 trace。429/503 对创建、恢复、付费调用均不自动重试。

同一用户和 Idempotency-Key、同一请求哈希返回同一任务，不同请求哈希返回 409；键绑定持久化，以防重启重复提交。内部 providerAttemptId 与任务持久化，外部超时不能推断未消费。

### 5.4 指标与样本口径

- 常规记录：输入/输出尺寸、格式、文件体积、处理耗时、峰值内存测量条件、实际执行算法、模型哈希、参数、跳过原因和降级原因。
- PSNR/SSIM：仅对配准且尺寸一致的干净 ground_truth；不把 source 修图参考当干净真值。
- ΔE：仅在已对齐且声明为未改动的有效区域计算；记录色彩空间、配准与 mask 版本。缺条件时返回 null 和 reason。
- 算法未输出可解释热图/掩码时，不在前端伪造；如新增诊断计算，应独立标为应用侧派生指标并验证定义。
- 模型效果验收使用独立、合法、脱敏的小样本集；保存明确的人工检查项，不用固定“平均提升百分比”替代真实结果。
- 大图、EXIF、缩放纹理、白灰/线稿参考、故意调色、没有足够未修改区域等必须进入边界样本，区分拒绝、跳过、失败与可处理。

## P00：冻结需求、标准映射和验收口径

**输入：** 本计划、docs/standards/ 下两份 L0 标准副本及第 1.1 节的来源/哈希基线、用户的本地部署与图像修复测试目标。无前置交接。

**创建文件：**

- `G:/project/RepairAiImage/docs/SPEC.md`
- `G:/project/RepairAiImage/docs/ARCHITECTURE.md`
- `G:/project/RepairAiImage/docs/FRONTEND_ARCHITECTURE.md`
- `G:/project/RepairAiImage/docs/API_CONTRACT.md`
- `G:/project/RepairAiImage/docs/TEST_PLAN.md`
- `G:/project/RepairAiImage/docs/adr/0001-local-identity-and-storage.md`
- `G:/project/RepairAiImage/docs/handoffs/P00.md`、`G:/project/RepairAiImage/docs/handoffs/P00.json`

### P00.1 形成项目基线

- [x] 读取项目内两份标准副本，核对 SHA-256 与第 1.1 节基线一致，并将结果写入 P00 交接；不一致时先查明差异并完成标准变更审查。将本文第 1、5 节映射为项目约束矩阵：原文条款 → 实现文件 → 负责阶段 → 验收项。
- [x] SPEC 列出四模块、七类模式、用户角色、输入输出、禁止宣称的能力和 M1/M2/M3 范围；为每项分配固定需求编号。
- [x] 架构文档画出依赖关系；明示 core 协议、repo 存储实现、infra 适配、service 编排与 api 组合根，防止“分层目录存在但调用绕过”。
- [x] ADR 记录本地 Basic 默认、HTTPS 边界、真实身份来源、单实例独占锁、原子 JSON 存储和不采用数据库的理由。已有企业身份条件只作为可替换输入，不能让实施者暗中放开认证。

### P00.2 冻结页面、契约和验收矩阵

- [x] 画出工作台、任务列表/详情、评估、系统四页面低保真布局；定义默认中文、浅色主题、主色 #1677ff、1440/1024/768 三个视口，768 下堆叠面板。
- [x] 确定 Token：4/8/12/16/24/32 间距、基础字号 14、表格默认 20 条；所有语义颜色从 Ant Token 映射。与团队品牌要求有冲突时在本阶段记录替换值。
- [x] API_CONTRACT 纳入第 5.3 节全部接口、DTO 字段约束、状态机、SSE、权限、错误、幂等和手动恢复协议。
- [x] TEST_PLAN 将每项需求映射为测试层级、样本和证据；分开“代码静态通过”“真实算法通过”“目标机部署通过”。
- [x] 固定性能测量设备、浏览器、网络、数据规模和采样方法；以前端标准建议的 LCP P75 ≤ 2.5s、INP P75 ≤ 200ms、CLS P75 ≤ 0.1 为候选预算，结合本地部署范围确认实际门槛和例外。分开统计前端渲染与推理延迟；实验室少量样本不能宣称真实用户 P75 达标。无真实用户数据时记录实验室代理结果及局限。冻结键盘导航、焦点顺序、可访问名称和比较工具替代操作的验收用例。
- [x] 在 P00 交接中列出需 P01 验证的上游假设，列明任何缺失的真实样本/身份集成条件，不能将假设写为验证结果。

**验证命令：**

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'G:/project/RepairAiImage/docs/standards/通用架构设定.md', 'G:/project/RepairAiImage/docs/standards/通用前端设定.md'
Get-ChildItem -LiteralPath 'G:/project/RepairAiImage/docs' -File
```

**通过条件：** 每项需求都有归属；状态与权限无未定义分支；契约覆盖手动恢复和外部调用未知结果；文档没有密钥、空白决策或伪造数据。此阶段为文档审查，不制造无意义单元测试。

**输出 → P01：** P00 交接、SPEC、两份项目架构、API_CONTRACT、TEST_PLAN 和标准哈希。建议提交：`docs: define repair platform baseline and acceptance contracts`，仅在执行阶段已建立 Git 后提交。

## P01：固定上游、建立真实样本与本地可运行基线

**输入：** `G:/project/RepairAiImage/docs/handoffs/P00.md` 及其索引。需要联网获取上游的操作在本阶段执行，发布包运行时不得重复执行。

**创建文件：**

- `G:/project/RepairAiImage/vendor/repair-ai-image-quality/`（固定提交的上游副本，保存 LICENSE 和来源）
- `G:/project/RepairAiImage/docs/UPSTREAM_BASELINE.md`
- `G:/project/RepairAiImage/docs/ENGINE_CAPABILITY_MATRIX.md`
- `G:/project/RepairAiImage/docs/fixtures/manifest.yaml`
- `G:/project/RepairAiImage/tests/fixtures/images/`（仅合法可提交的最小样本）
- `G:/project/RepairAiImage/docs/evidence/P01/`、`G:/project/RepairAiImage/docs/handoffs/P01.md`、`P01.json`

### P01.1 获取并盘点固定版本

- [ ] 核验仓库归属、README、源码、根许可证和两个 ONNX 的来源/单独许可证；记录下载来源、提交哈希、文件哈希、依赖与模型体积。
- [ ] 在隔离临时目录取得上游，验证候选提交存在后将固定版本导出到 vendor；不要嵌套残留 `.git`，不执行其安装脚本后再做来源检查。
- [ ] 逐个核对 selftest、基础修复、source、chain、paste-back、controller、portrait、transplant 的帮助与源码；记录准确命令、cwd、输出命名、退出码与必要环境变量。
- [ ] 建立 ENGINE_CAPABILITY_MATRIX：模式 → CLI/入口 → 必需角色 → 参数范围 → 模型/外部条件 → 原始输出 → UI 可展示指标 → 降级行为。
- [ ] 对上游 bootstrap、`--wash-cmd`、shell 调用和 EXIF/大图跳过逻辑做定点检查；记录包装器如何绕过运行时联网，以及应用禁止接收浏览器 shell 字符串的边界。

### P01.2 跑上游基线并形成可复验样本

- [ ] 依据上游已核验依赖在隔离环境准备运行时；运行自检并保存完整退出码、用时和报告。失败须定位到模型缺失、环境问题或算法问题，不能只保留最后一行。
- [ ] 准备编号：D01 典型迷宫纹、D02 无噪声、D03 大图/EXIF、D04 缩放后纹理；C01 偏色+真实 source、C02 白灰 source、C03 故意调色；P01 局部编辑；B01 两张混合批量；E01 带真值；X01 最小移植样本。
- [ ] 每个样本在 manifest 中记录许可/授权、角色、尺寸、SHA-256、预期处理/跳过/人工复核类别；不把含敏感人脸的真实业务图随意入库。
- [ ] 对每个基础模式运行真实算法，保存原始制品与 JSON；验证缺模型时是明确失败还是谱域降级，并记录实际 engineUsed。
- [ ] 测量固定设备上的耗时和内存，记录 CPU/内存/OS、输入尺寸、冷/热启动、重复次数及原始数据；不使用 README 的宣传耗时代替本机基准。

**计划运行命令：** 先通过已核验帮助确认语法，再执行以下上游入口，不将未核验参数硬编码进适配器。

```powershell
Set-Location -LiteralPath 'G:/project/RepairAiImage/vendor/repair-ai-image-quality'
powershell -ExecutionPolicy Bypass -File './scripts/run.ps1' selftest
powershell -ExecutionPolicy Bypass -File './scripts/run.ps1' --help
```

**通过条件：** 基础模式真实执行产物存在；自检结果有证据；模型授权可交付；准确入口表已确认；降级可识别。模型授权不清晰时阻止携带该模型发布，不能以根 MIT 自动推定全部权重许可。

**输出 → P02：** P01 交接、固定 vendor、能力矩阵、样本 manifest、自检与基准、依赖/许可证表。P02 只依据此表选依赖；P04 只依据此表做参数映射。建议提交：`chore: pin upstream engine and reproducible fixtures`。

## P02：建立工程、开发入口和质量门禁

**输入：** P01 交接及其上游/样本/架构索引。

**创建文件：**

- `G:/project/RepairAiImage/package.json`、`package-lock.json`、`.gitignore`、`.editorconfig`
- `G:/project/RepairAiImage/backend/pyproject.toml`、`requirements.lock`、`src/api/app.py`
- `G:/project/RepairAiImage/frontend/package.json`、`tsconfig.json`、`vite.config.ts`、`src/main.tsx`
- `G:/project/RepairAiImage/tools/run-python.mjs`、`dev.mjs`、`check-boundaries.mjs`、`check-handoff.mjs`
- `G:/project/RepairAiImage/.github/workflows/ci.yml`
- `G:/project/RepairAiImage/docs/TECH_STACK.md`、`docs/handoffs/P02.md`、`P02.json`

### P02.1 固定兼容版本和最小骨架

- [ ] 根据 P01 确定一个受支持的 Python 稳定版本、Node LTS/npm，以及互相兼容的 React/Ant/ProComponents/Router/Storybook/测试工具版本；实际安装验证后记录精确版本、选择依据与限制。
- [ ] 初始化独立 Git 仓库（仅在确认目录仍未处于其他仓库时）；忽略 `.venv`、node_modules、data、dist、私密证据、`.env` 和临时缓存，保留锁文件和必要可分发模型。
- [ ] 创建工作区与最小 FastAPI/Vite 工程；首版页面只有受控占位与错误边界，不把模拟任务写为成功。
- [ ] 建立后端 `backend/.venv`，锁定 Python 依赖与哈希；根 npm 脚本按第 4 节提供稳定入口。测试转发器的 pytest 工作目录为 backend，输入路径从 backend 开始。
- [ ] 为进程启动器写能发现“已有端口被占用/子进程异常退出/关闭后遗留进程”的测试，再实现启动与清理；3000 冲突直接报错，不自动换端口。

### P02.2 让门禁先工作

- [ ] 为分层检查器加入故意违法的临时 fixture：core 导入 service、shared 导入 modules；先确认检查失败，再实现规则使正常工程通过。
- [ ] 为交接检查器加入缺输出、哈希错、失败证据、下游缺前置的 fixture；确认都被拒绝后补录 P00/P01 真实清单。
- [ ] 建立 OpenAPI 导出与 `openapi-typescript` 类型生成，检查生成物漂移，不手改 generated 文件。
- [ ] CI 顺序采用 npm ci → 静态/安全/许可证/来源/重复依赖 → 单元/组件/契约 → 应用和 Storybook 构建 → E2E/视觉 → 部署冒烟。尚未实现的业务阶段只运行已存在的测试，禁止空脚本永远返回成功。
- [ ] pytest 警告按错误处理，ESLint 使用 `--max-warnings 0`；对构建/审计警告建立显式允许清单和理由，没有“全部忽略”。

**验证命令：**

```powershell
Set-Location -LiteralPath 'G:/project/RepairAiImage'
py -m venv './backend/.venv'
& './backend/.venv/Scripts/python.exe' -m pip install --require-hashes -r './backend/requirements.lock'
npm install
npm run check
npm test
npm run build
npm run check:handoff -- P02
```

首次生成 requirements.lock 必须先使用同 Python 版本的锁定工具求解；上面的安装命令在锁文件已生成后运行。CI 使用 npm ci；禁止 `--force`/`--legacy-peer-deps` 掩盖冲突。

**通过条件：** 从干净目录可安装；dev 端口正确且关闭无孤儿；所有现有检查通过；故意违约的门禁 fixture 会失败。此阶段不声称业务 E2E 已完成。

**输出 → P03：** 可复现工程、版本锁、根命令、最小 OpenAPI、工作的 CI/架构门禁、P02 交接。建议提交：`chore: bootstrap typed workspace and quality gates`。

## P03：配置、认证、trace 与私有文件底座

**输入：** P02 工程与命令，P00 权限/配置约束，P01 上传与样本约束。

**创建/修改文件：**

- `G:/project/RepairAiImage/backend/src/core/config.py`、`errors.py`、`models.py`、`ports.py`
- `G:/project/RepairAiImage/backend/src/infra/auth.py`、`logging.py`、`trace.py`
- `G:/project/RepairAiImage/backend/src/repo/artifact_repository.py`
- `G:/project/RepairAiImage/backend/src/service/upload_service.py`
- `G:/project/RepairAiImage/backend/src/api/dto.py`、`dependencies.py`、`routes/uploads.py`、`routes/session.py`、`routes/health.py`
- `G:/project/RepairAiImage/backend/src/core/test_config.py`、`repo/test_artifact_repository.py`、`service/test_upload_service.py`
- `G:/project/RepairAiImage/backend/tests/test_security_contract.py`、`test_upload_contract.py`
- `G:/project/RepairAiImage/deploy/config.example.yaml`、`docs/handoffs/P03.md`、`P03.json`

### P03.1 先验证配置和身份的拒绝路径

- [ ] 先写参数化测试：默认→全局→实例→env 覆盖正确；未知字段拒绝；实例注入认证/密钥/隔离字段拒绝；缺凭据、模型必需项或不可写 data 启动失败。
- [ ] 写 API 测试：非免鉴权路径无凭据为 401，viewer 创建为 403，受控凭据重载成功后旧凭据下一请求失效、环境变量凭据在受控重启后失效，用户 A 不能读取用户 B 的文件；错误体/trace 一致。
- [ ] 运行上述测试确认失败后，实现 Pydantic 配置、core 错误枚举、身份与权限中间件、依赖注入；配置摘要记录来源且脱敏。
- [ ] 入站合法 trace 透传，非法 trace 重建；注入 Authorization、Cookie、密钥样本验证日志不含原文；底层 cause 仅入受控日志。
- [ ] 为实际响应设置并测试 X-Content-Type-Options、Referrer-Policy、Permissions-Policy，以及 X-Frame-Options/CSP frame-ancestors；HSTS 仅在 HTTPS 入口启用，受信代理信息由明确配置确定。CSP 先按页面资源清单以 Report-Only 验证，再切换强制策略并测试允许/阻止结果；报告模式不能作为阻止攻击的验收证据。测试覆盖页面、静态资源、API 和错误响应，生产入口在 P12 重验。
- [ ] 实现 healthz/readyz；可选云 provider 缺凭据不使基础修复全局不可用，必需本地模型缺失则按 P01 降级政策报告 readiness，不对外泄露物理路径。

### P03.2 交付安全上传和私有文件

- [ ] 先写测试：伪扩展名、解码失败、空文件、尺寸/像素/体积超限、路径穿越、他人 uploadId、过期文件、重复引用冲突、磁盘满。
- [ ] 实现服务端签名/解码校验、流式体积限制、像素上限和随机 ID；保留供算法判断所需的 EXIF 信息但对外展示脱敏，不能因预处理提前丢失上游跳过条件。
- [ ] 文件仓储只实现受 data 根约束的读写/原子替换/元数据；上传服务决定权限、过期与引用规则。用户文件名仅作展示，不能形成实际磁盘路径。
- [ ] 以两个真实测试账号验证上传/查询/删除隔离；只有经过 service 校验的 artifactId 可被路由读取，不使用公开静态目录暴露结果。
- [ ] 为结构化日志设置大小、轮转、丢弃/落盘失败计数；管理员诊断能读取这些状态，避免静默丢失错误。

**测试示例（先红后绿，放入 test_security_contract.py）：**

```python
def test_operator_cannot_read_other_users_upload(client, operator_b_auth, upload_owned_by_a):
    response = client.delete(
        f"/api/v1/uploads/{upload_owned_by_a}",
        headers=operator_b_auth,
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "UPLOAD_NOT_FOUND"
    assert response.headers["x-trace-id"] == response.json()["trace_id"]
```

fixture 在 `G:/project/RepairAiImage/backend/tests/conftest.py` 定义：client 使用独立 tmp data；operator_b_auth 是 B 账号 Basic header；upload_owned_by_a 通过 A 账号调用上传接口创建。错误 404 防止枚举他人资源，错误码在 core/errors.py 注册。

**验证：**

```powershell
npm run test:backend -- src/core/test_config.py src/repo/test_artifact_repository.py src/service/test_upload_service.py tests/test_security_contract.py tests/test_upload_contract.py -q
npm run api:generate
npm test
npm run check
npm run check:handoff -- P03
```

**通过条件：** 配置拒绝路径真实生效；两个账号隔离成立；上传不能逃出 data 根；日志无凭据；health/readiness 语义正确。

**输出 → P04：** 配置/身份/错误/trace/文件协议与实现、上传 OpenAPI、权限证据、P03 交接。建议提交：`feat: add authenticated configuration and private uploads`。

## P04：任务持久化、上游执行、取消与恢复

**输入：** P03 安全与文件底座，P01 固定入口与原始输出，P00 状态/幂等/SSE 契约。

**创建/修改文件：**

- `G:/project/RepairAiImage/backend/src/repo/task_repository.py`
- `G:/project/RepairAiImage/backend/src/service/task_service.py`、`repair_service.py`
- `G:/project/RepairAiImage/backend/src/infra/process_runner.py`、`repair_engine_adapter.py`
- `G:/project/RepairAiImage/backend/src/api/routes/tasks.py`、`events.py`、`capabilities.py`
- `G:/project/RepairAiImage/backend/src/repo/test_task_repository.py`、`service/test_task_service.py`
- `G:/project/RepairAiImage/backend/tests/test_task_api.py`、`test_process_lifecycle.py`、`test_task_recovery.py`、`test_sse.py`
- `G:/project/RepairAiImage/docs/handoffs/P04.md`、`P04.json`

### P04.1 先实现持久化状态和幂等

- [ ] 为允许/禁止状态迁移、version 冲突、同键同请求、同键异请求、重启重复提交写失败测试，再实现 task service；仓储仅做原子读写与版本条件更新。
- [ ] 任务输入在创建时冻结 uploadId/哈希/角色/参数/owner/upstreamVersion/modelHash；数据缺失不创建半有效排队项。
- [ ] 获得单实例锁，恢复任务索引；中断任务的处理按第 5.2 节执行，不默认重跑外部操作。
- [ ] 进程启动意图先持久化；用 Windows Job Object（关闭即终止进程树）或同等可验证机制管理子孙进程，存储 PID+创建时间，禁止仅凭重用 PID 杀进程。

### P04.2 接入真实引擎并限制资源

- [ ] 用可控测试子程序验证超时、非零退出、非法 JSON、输出缺失、超大日志和父进程崩溃，再实现 process runner。
- [ ] 上游适配器从 P01 表生成固定参数数组，使用 `shell=False`；文件名含空格、中文、单引号、`&`、`$()` 的用例必须原样传递，不能被解释为命令。
- [ ] 首版默认并发 1、队列上限 20、执行超时 300 秒、上传上限 50 MiB/张与 4000 万像素；作为配置白名单，P01 实测若需调整，在 ADR/能力接口同步修改后锁定。
- [ ] 只有后台 worker 执行阻塞图像处理；HTTP 创建接口在排队后返回 202。队列满返回 429+Retry-After；大文件解码也放入受限执行器。
- [ ] 实跑一张 D01，解析原始 JSON、fixed 与 compare 制品；保留 rawMetadataVersion，不因字段缺失默认为 0 或假成功。

### P04.3 实现取消、重启和 SSE

- [ ] 写排队取消、运行取消、已终态取消、取消与完成竞争、进程树残留用例；按 version 序列化竞争，实际子进程终止后才发布 canceled。
- [ ] 写“杀掉 worker/重启 API/重新连接”的集成用例，证明没有静默重复执行，未完成任务和可下载制品状态一致。
- [ ] SSE 同源鉴权、心跳、eventId、快照/reset、Last-Event-ID 重连和终态关闭；断开客户端连接不会触发取消。
- [ ] 持久化事件先于发送；受控保留最近事件，写失败发出诊断告警并使相关状态更新失败，不能向前端宣布未落盘的成功。

**测试示例（放入 service/test_task_service.py）：**

```python
def test_retry_creates_new_task(task_service, failed_task, operator_a):
    retried = task_service.retry(failed_task.id, operator_a)
    assert retried.id != failed_task.id
    assert retried.retry_of == failed_task.id
    assert retried.status == "queued"
    assert task_service.get(failed_task.id, operator_a).status == "failed"
```

fixture 用真实文件仓储和可控执行器构造；另用 test_process_lifecycle.py 测真实 OS 进程，不能只证明 mock 收到 terminate。

**验证：**

```powershell
npm run test:backend -- src/repo/test_task_repository.py src/service/test_task_service.py tests/test_task_api.py tests/test_process_lifecycle.py tests/test_task_recovery.py tests/test_sse.py -q
npm run api:generate
npm test
npm run check
npm run check:handoff -- P04
```

**通过条件：** 一项真实算法任务有可下载制品；状态/事件/磁盘一致；取消无残留进程；重启不重复付费或静默重跑；HTTP 未被处理任务阻塞。

**输出 → P05：** 稳定任务 API、真实处理样本、状态/SSE 协议、可用制品、恢复证据、P04 交接。建议提交：`feat: implement durable repair tasks and process lifecycle`。

## P05：前端主题、模板、请求与实时状态基础

**输入：** P04 真实任务 API/样本、P00 前端约束和页面布局、P02 锁定工具链。

**创建/修改文件：**

- `G:/project/RepairAiImage/frontend/src/app/providers.tsx`、`router.tsx`、`error-boundary.tsx`
- `G:/project/RepairAiImage/frontend/src/layouts/admin-layout.tsx`
- `G:/project/RepairAiImage/frontend/src/design-system/tokens.ts`、`antd-theme.ts`、`chart-theme.ts`、`templates/`
- `G:/project/RepairAiImage/frontend/src/shared/api/http.ts`、`errors.ts`、`shared/auth/session.ts`
- `G:/project/RepairAiImage/frontend/src/shared/hooks/use-task-events.ts`
- `G:/project/RepairAiImage/frontend/src/shared/components/query-state.tsx`、`permission-gate.tsx`、`status-tag.tsx`、`task-progress.tsx`、`trace-id-text.tsx`、`confirm-action.tsx`
- `G:/project/RepairAiImage/frontend/.storybook/main.ts`、`preview.tsx`
- `G:/project/RepairAiImage/frontend/src/shared/api/http.test.ts`、`shared/hooks/use-task-events.test.tsx`
- `G:/project/RepairAiImage/frontend/tests/e2e/foundations.spec.ts`、`visual/foundations.spec.ts`
- `G:/project/RepairAiImage/docs/handoffs/P05.md`、`P05.json`

### P05.1 先统一单一数据流与身份

- [ ] 再生 API 类型，模块 api.ts 仅封装 Axios；queries.ts 作为 SWR 唯一查询入口，禁止 Router loader 再建长期缓存或 ProTable request 另发请求。
- [ ] 先写 HTTP 客户端测试：401 会话提示；403 不重试；409 提示刷新；422 字段映射；429 读取 Retry-After；500 展示 trace；写请求不自动重试，再实现统一转换。
- [ ] 读取真实 `/session` 控制菜单与操作；权限组件只负责展示，禁止模拟用户作为业务验收身份。
- [ ] 在 Vite 最前置中间件将页面、静态资源和开发连接的认证校验转交后端 session；后端不可用时拒绝访问，3000 仅绑定 loopback，不允许无保护 dev server 暴露业务图片。
- [ ] 路由四模块懒加载，定义错误边界、无权限/404 页面；Axios、SWR provider 与 Ant App/ConfigProvider 只初始化一次。

### P05.2 落地模板、组件与 Storybook

- [ ] 实现列表、详情、工作台、分析、配置/诊断模板与 ProLayout；严格读取 Token，不在业务 CSS 写一套未定义颜色/字号。
- [ ] 为公共组件建立 loading/empty/error/forbidden/long-text/narrow/disabled 状态，补键盘操作和可访问标签。
- [ ] 每个公共组件有 stories，Storybook 使用明确标记的样本数据，内部访问受控；应用业务路由仍连接真实 API。
- [ ] 对 SSE 写测试：重复 eventId 不重复应用、断线显示异常、重新连接取快照、版本较旧事件被忽略、终态停止、卸载清理；实现后通过后端 P04 重连用例。
- [ ] 用 SWR mutate 更新任务权威快照，不把整个 task 再复制进 Zustand；纯缩放/抽屉/选择状态使用 React local state。

### P05.3 固定视觉基线

- [ ] 固定 Playwright 浏览器构建、OS、字体、1440/1024/768 视口、样本、时间、时区与动画；截图只屏蔽已明确的动态字段，不能屏蔽整个业务结果。
- [ ] 执行组件/模板首轮截图并人工审查后保存基线；禁止以自动更新快照替代审查。
- [ ] 记录基础壳的 bundle 体积、懒加载边界，确认 ECharts 仅按需注册；不默认安装 Monaco 或其他重型编辑器。
- [ ] 在 P00 固定环境下测量基础页面性能并保留原始报告；对照约定预算核查，推理耗时单列。用自动化与人工检查验证键盘可达、焦点恢复、表单标签、状态播报及图片比较的键盘替代操作；P06/P09 补齐真实页面，P12 在目标入口复验。

**验证：**

```powershell
npm run test:frontend -- src/shared/api/http.test.ts src/shared/hooks/use-task-events.test.tsx
npm run check
npm run build
npm run build:storybook
npm run test:e2e -- --grep foundations
npm run test:visual -- --grep foundations
npm run check:handoff -- P05
```

**通过条件：** 四路由可达且鉴权；公共状态完整；SWR 单数据源；首轮视觉审核留痕；3000 访问不能绕过后端身份。

**输出 → P06：** 可复用前端壳、组件与主题、生成类型、真实请求/SSE hooks、Storybook 和视觉基线、P05 交接。建议提交：`feat: establish frontend templates and authenticated data flow`。

## P06：基础迷宫纹修复端到端闭环（M1）

**输入：** P05 前端基础；沿交接索引读取 P04 引擎/任务与 P01 D01–D04 样本。

**创建/修改文件：**

- `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/api.ts`、`queries.ts`、`schemas.ts`、`types.ts`、`index.ts`
- `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/pages/repair-workbench-page.tsx`
- `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/components/mode-form.tsx`
- `G:/project/RepairAiImage/frontend/src/shared/components/image-upload-field.tsx`、`image-compare-viewer.tsx`、`synchronized-zoom-viewer.tsx`、`repair-metric-panel.tsx`、`artifact-list.tsx`、`json-viewer.tsx`
- `G:/project/RepairAiImage/backend/tests/test_demaze_acceptance.py`
- `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/components/mode-form.test.tsx`
- `G:/project/RepairAiImage/frontend/tests/e2e/demaze.spec.ts`、`visual/workbench.spec.ts`
- `G:/project/RepairAiImage/docs/handoffs/P06.md`、`P06.json`

### P06.1 工作台连接真实修复

- [ ] 先写模式表单测试：必需图片、合法 strength、超限参数、上传失败保留表单、重复点击仅一次创建；再实现前端字段校验，后端仍重复校验。
- [ ] 顶部显示实际能力与模式；左栏上传/参数；中间原图/结果/对比滑杆；下方耗时、尺寸、实际算法、制品；抽屉原始 JSON 与 trace。
- [ ] 创建请求由后端幂等键去重；表单提交返回 taskId 后订阅 SSE，刷新页面从 URL taskId 恢复，同一任务不被再次创建。
- [ ] 实现同步缩放/平移、原始尺寸查看与本地 Blob 预览回收；不同尺寸不伪装对齐，明确显示缩放方式。
- [ ] 比较图只用于展示；原始输入和实际结果分别提供受控下载，下载失败不误显示成功。

### P06.2 验证模型效果与例外

- [ ] 在无 mock 引擎条件下跑 D01，断言任务终态、模型/上游哈希、输出可解码、尺寸/制品角色一致；人工对迷宫纹、细节损失、色彩漂移逐项评审。
- [ ] 跑 D02/D03/D04，核对 skip/fallback/低置信度的实际表现；前端显示原因，不能用一个绿色“完成”吞掉“未处理”。
- [ ] 重复 P04 的运行取消与重启恢复，加入浏览器刷新、断网重连、viewer 无创建权限路径。
- [ ] 对比 P01 原始基线，确保适配器参数与输出解释没有改变算法；若出现差异，先修映射，禁止直接改 vendor 算法掩盖。
- [ ] 补本阶段新增共享组件 stories 和视觉截图，审查 768 视口下拖动比较、文件长名、错误和等待状态。

**真实 E2E 断言示例（demaze.spec.ts，浏览器使用 operator HTTP credentials）：**

```typescript
import { expect, test } from '@playwright/test';

test('demaze real engine completes and exposes artifacts', async ({ page }) => {
  await page.goto('/repair');
  await page.getByLabel('输入图片').setInputFiles('tests/fixtures/demaze.png');
  await page.getByRole('button', { name: '开始修复', exact: true }).click();
  await expect(page.getByTestId('task-status')).toHaveAttribute('data-status', 'succeeded', { timeout: 300_000 });
  await expect(page.getByTestId('engine-used')).not.toHaveText('mock');
  await expect(page.getByRole('link', { name: '下载修复图', exact: true })).toBeVisible();
});
```

`G:/project/RepairAiImage/frontend/tests/fixtures/demaze.png` 由 P01 合法 D01 样本准备脚本按 SHA 校验后复制；不是随意替换的截图。该用例还应通过 API 核对 engineUsed 与模型哈希；仅上述“不是 mock”断言不足以证明 ONNX 执行。

**验证：**

```powershell
npm run test:backend -- tests/test_demaze_acceptance.py -q
npm run test:frontend -- src/modules/repair-workbench/components/mode-form.test.tsx
npm run test:e2e -- --grep demaze
npm run test:visual -- --grep workbench
npm run verify
npm run check:handoff -- P06
```

**通过条件：** 真实身份→上传→执行→进度→刷新恢复→比较→下载闭环；ONNX 与 fallback 的证据明确分开；所有异常状态可见；适用测试和视觉审核通过。

**输出 → P07：** M1 可运行版本、工作台样板、真实模型验收报告、公共图片组件、P06 交接。建议提交：`feat: deliver real demaze repair workflow`。

## P07：颜色校正、多轮链式与贴回

**输入：** P06 已验收工作台，P01 C01–C03/P01 样本及各模式准确命令，P00 指标与角色契约。

**创建/修改文件：**

- `G:/project/RepairAiImage/backend/src/service/repair_service.py`
- `G:/project/RepairAiImage/backend/src/infra/repair_engine_adapter.py`
- `G:/project/RepairAiImage/backend/src/service/test_repair_service.py`
- `G:/project/RepairAiImage/backend/tests/test_color_chain_pasteback.py`
- `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/components/color-form.tsx`、`chain-form.tsx`、`pasteback-form.tsx`、`chain-results.tsx`
- `G:/project/RepairAiImage/frontend/tests/e2e/color-chain-pasteback.spec.ts`
- `G:/project/RepairAiImage/docs/handoffs/P07.md`、`P07.json`

### P07.1 颜色校正

- [ ] 先写缺 source、错误角色、尺寸/配准不满足、白灰/线稿/无足够未修改区域的测试；后端返回可理解的拒绝或 skip reason，不猜测 source。
- [ ] 实现 source+edit+可选 mask 表单；前端说明参考图应有真实色彩，保留用户输入，提示有意调色时谨慎校正。
- [ ] 用 C01 实跑并记录校正结果与有效区域；C02/C03 验证跳过/保护区逻辑，不把所有色差都当成应修问题。

### P07.2 链式与贴回

- [ ] 先写 sequence 唯一/连续、缺轮次、重复文件、最早 source 固定的测试；再实现显式排序和每轮相对最早原图的调用映射。
- [ ] 链式结果按 round 显示每轮图、参数、状态、指标与制品；一轮失败保留已完成结果并终止需依赖该轮的后续步骤。
- [ ] 贴回用原始分辨率坐标和明确编辑区域；对 P01 局部编辑样本逐像素比较未修改区域，确认承诺范围内与原图相同。
- [ ] 只有输入满足上游条件时提供“未修改区域一致”结论；涉及重采样/有损编码时用匹配的比较定义并披露，不能用 PNG 断言套到 JPEG。
- [ ] 更新 capabilities、OpenAPI、类型、表单 schema、stories 和 E2E；禁止仅根据 UI 下拉框选项判断能力完成。

**验证：**

```powershell
npm run test:backend -- src/service/test_repair_service.py tests/test_color_chain_pasteback.py -q
npm run api:generate
npm run test:e2e -- --grep color-chain-pasteback
npm test
npm run check
npm run check:handoff -- P07
```

**通过条件：** 三类模式均有真实输入/输出；source/顺序/贴回坐标的错误用例通过；每轮原始结果可追溯；没有伪造 ΔE/PSNR。

**输出 → P08：** 四种核心处理模式（含基础修复）的真实产物与契约，P07 交接。建议提交：`feat: add reference color chain and pasteback modes`。

## P08：任务中心、系统诊断与数据生命周期

**输入：** P07 模式与真实任务样本，P04 任务状态/制品/取消/恢复，P03 权限与日志。

**创建/修改文件：**

- `G:/project/RepairAiImage/frontend/src/modules/tasks/api.ts`、`queries.ts`、`types.ts`、`index.ts`、`pages/task-list-page.tsx`、`pages/task-detail-page.tsx`
- `G:/project/RepairAiImage/frontend/src/modules/system/api.ts`、`queries.ts`、`types.ts`、`index.ts`、`pages/system-page.tsx`
- `G:/project/RepairAiImage/backend/src/service/cleanup_service.py`、`system_service.py`
- `G:/project/RepairAiImage/backend/src/api/routes/system.py`
- `G:/project/RepairAiImage/backend/src/service/test_cleanup_service.py`
- `G:/project/RepairAiImage/backend/tests/test_task_management.py`、`test_system_diagnostics.py`
- `G:/project/RepairAiImage/frontend/tests/e2e/task-management.spec.ts`、`system.spec.ts`
- `G:/project/RepairAiImage/docs/handoffs/P08.md`、`P08.json`

### P08.1 受控列表与任务管理

- [ ] 先写组件测试：URL 筛选/分页/排序→SWR key→单次请求，返回后恢复筛选；ProTable 不配置独立 request。
- [ ] 列表展示模式、状态、子项成功/跳过/失败数、时间、实际算法/provider、owner；详情共用结果组件，不复制工作台业务逻辑。
- [ ] 取消/重试/清理均有权限和确认；响应 409 时刷新权威状态；重试跳转新 taskId，不把旧记录改成排队。
- [ ] 用已完成、运行、等待人工、部分失败、全跳过、长文件名等真实/受控后端样本验证 UI，不靠静态前端假对象完成验收。

### P08.2 诊断与清理

- [ ] 系统页显示 engine/model 哈希、缺失模型、降级、磁盘容量、任务队列、日志落盘异常、provider 可用原因；密钥始终不返回。
- [ ] 清理先标记 tombstone，再删制品和元数据；异常中断可重入。运行任务、正在写出的制品和被引用文件拒绝清理。
- [ ] 默认未绑定上传 24 小时过期，终态任务保留 7 天；管理配置可修改白名单保留值。持久化引用计数或反向索引，不能只按文件修改时间删除。
- [ ] 服务端扫描批次受限；先清任务/评估引用，再清独立上传；在磁盘满、权限不足、文件已不存在时产生可查询结果和告警。
- [ ] 日志接口管理员权限、cursor 分页、脱敏与大小上限；前端不一次加载全部日志。

**验证：**

```powershell
npm run test:backend -- src/service/test_cleanup_service.py tests/test_task_management.py tests/test_system_diagnostics.py -q
npm run test:e2e -- --grep 'task-management|system'
npm run test:visual
npm test
npm run check
npm run check:handoff -- P08
```

**通过条件：** 列表刷新恢复、权限正确、取消/重试真实生效；清理不误删活跃/引用文件；系统缺依赖的展示与 readyz/capabilities 一致。

**输出 → P09：** 完整任务中心、只读系统诊断、可复用安全清理机制、真实状态样本、P08 交接。建议提交：`feat: add task management diagnostics and retention`。

## P09：批量评估、指标和报告（M2）

**输入：** P08 生命周期与管理，P07 各模式，P01 E01/B01 和数据口径。

**创建/修改文件：**

- `G:/project/RepairAiImage/backend/src/core/evaluation_models.py`
- `G:/project/RepairAiImage/backend/src/repo/evaluation_repository.py`
- `G:/project/RepairAiImage/backend/src/service/evaluation_service.py`、`metric_service.py`、`report_service.py`
- `G:/project/RepairAiImage/backend/src/api/routes/evaluations.py`
- `G:/project/RepairAiImage/backend/src/service/test_metric_service.py`、`test_report_service.py`
- `G:/project/RepairAiImage/backend/tests/test_evaluation_workflow.py`
- `G:/project/RepairAiImage/frontend/src/modules/evaluation/api.ts`、`queries.ts`、`types.ts`、`index.ts`、`pages/evaluation-page.tsx`
- `G:/project/RepairAiImage/frontend/tests/e2e/evaluation.spec.ts`
- `G:/project/RepairAiImage/docs/METRICS.md`、`docs/handoffs/P09.md`、`P09.json`

### P09.1 批量编排和数据配对

- [ ] 先写配对测试：manifest 显式 sampleId 和角色；缺真值、重复 ID、错尺寸、不同权限文件拒绝，不能按目录顺序暗中配对。
- [ ] 评估记录包含 datasetHash、engineVersion、modelHash、parameters、metricVersion、childTaskIds、createdBy；复用 P04 内核，不另建第二套队列。
- [ ] 支持按同一数据集比较参数组，预览预计任务数和上限；默认每次评估最多 100 个样本/参数组合，超限返回字段错误，不静默截断。
- [ ] 取消评估显式取消未完成子任务；已完成结果保留，报告包含取消/跳过/失败数。评估与任务清理互相检查引用。

### P09.2 定义可解释指标并导出

- [ ] 先写已知向量测试：相同图像 SSIM=1、PSNR 为正无穷时 JSON 用 null+reason=identical 及 isPerfect=true 表达，不能输出非标准 Infinity；不同图像、尺寸不符、mask 为空、无真值各有预期。
- [ ] 固定 SSIM 的色彩通道/data_range/window、PSNR 数值范围、ΔE 公式和色彩转换依赖版本；在 METRICS.md 给出计算范围与限制。
- [ ] 汇总只使用有效样本，显式 validCount/skippedCount/failedCount，不把缺指标按 0 纳入平均；不同 metricVersion 禁止混算。
- [ ] 报告包含样本哈希、模型/版本/参数、指标定义、原始值/无效原因、耗时统计、人工评价和 trace；ECharts 只展示真实可计算维度。
- [ ] 先写 CSV 注入测试（以 =、+、-、@、制表符/回车起始的用户字段）；实现安全转义、下载权限、大小上限和审计。JSON 报告禁止携带服务器绝对路径/凭据。
- [ ] 用 E01 真实跑一轮，用独立计算脚本核对数值；B01 验证部分失败/跳过统计，与任务列表逐项对账。

**验证：**

```powershell
npm run test:backend -- src/service/test_metric_service.py src/service/test_report_service.py tests/test_evaluation_workflow.py -q
npm run api:generate
npm run test:e2e -- --grep evaluation
npm run verify
npm run check:handoff -- P09
```

**通过条件：** 批量结果可按 manifest 重现；统计与子任务一致；无真值不显示 PSNR/SSIM；CSV 无公式执行风险；M2 四模块均有真实后端闭环。

**输出 → P10：** M2 核心验收版本、指标定义、真实批量与报告证据、P09 交接。建议提交：`feat: add reproducible batch evaluation and safe reports`。

## P10：手动增强闭环与可选外部服务

**输入：** P09 的 M2 版本、任务内核、可复验评估；沿交接链读取 P01 的 controller 命令清单与实际运行限制。

**创建/修改文件：**

- `G:/project/RepairAiImage/backend/src/core/enhancement_models.py`、`provider_contracts.py`
- `G:/project/RepairAiImage/backend/src/service/enhancement_service.py`
- `G:/project/RepairAiImage/backend/src/infra/providers/manual_provider.py`、`gemini_provider.py`、`fal_provider.py`
- `G:/project/RepairAiImage/backend/src/repo/provider_attempt_repository.py`
- `G:/project/RepairAiImage/backend/src/service/test_enhancement_service.py`
- `G:/project/RepairAiImage/backend/tests/test_enhancement_workflow.py`、`test_provider_safety.py`
- `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/components/enhancement-form.tsx`、`manual-input-panel.tsx`
- `G:/project/RepairAiImage/frontend/tests/e2e/enhancement.spec.ts`
- `G:/project/RepairAiImage/docs/ENHANCEMENT_GUIDE.md`、`docs/handoffs/P10.md`、`P10.json`

### P10.1 先完成不依赖云密钥的手动流程

- [ ] 将 P01 核验的 controller plan/融合/人像处理能力逐一映射为后端模式；没有验证通过的命令不加入可用能力列表。
- [ ] 先测试原图提交后产生持久化 inputRequest，状态为 running、stage 为 waiting_input；此时释放执行槽，刷新和重启后仍可继续。
- [ ] 等待面板显示需要“清洗图”或“超分图”、输入格式/尺寸/数量、参考原图和后续动作。文件通过 P03 上传接口提交，由服务器绑定 washed/upscaled 角色，不允许输入目标机目录。
- [ ] 恢复请求携带 inputRequestId、expectedVersion、上传引用和 Idempotency-Key；后端验证 owner、角色、尺寸/配准条件和当前请求版本。过期请求、重复恢复、其他用户文件均拒绝且不启动第二次融合。
- [ ] 等待请求默认 24 小时过期，可配置；到期转 failed/INPUT_EXPIRED，释放引用，记录原因。用户可通过新任务重试；不在终态任务上重开等待。
- [ ] 使用合法的手动清洗图与超分图分别跑真实融合，保存中间产物、实际命令、输出和比较图；SeedVR2 未安装时只显示手动超分导入，不显示已运行 SeedVR2。

### P10.2 按明确边界接入可选 provider

- [ ] provider 配置仅来自服务端配置/环境变量与受控凭据源；模型名、端点、输入上限、超时由管理员白名单约束。浏览器只选 capabilityId，不提交 shell、任意 URL 或 --wash-cmd。
- [ ] 单独定义可用条件：凭据已配置、端点允许、模型可访问、响应格式兼容；默认关闭远程发送。只证明配置存在时标记 configured，未经真实调用不得标记 live_verified。
- [ ] 创建远程任务前展示将上传的文件、接收服务、是否可能收费和调用次数上限；用户明确确认后才提交，审计记录 consent 与输入哈希。成本无法可靠估算时写“费用以服务商实际计费为准”，不显示虚假精确金额。
- [ ] 每次外部调用先持久化 providerAttemptId、taskId、输入哈希、consent、预算和状态，再发送；支持服务商原生幂等时使用其幂等键，仍不承诺所有服务商具有相同语义。
- [ ] 先测“请求已发出但响应丢失、重启、429、5xx、取消”场景；无法确定是否消费时持久化 PROVIDER_RESULT_UNKNOWN，禁止自动付费重试。管理员核对远程结果后，用户才能显式创建新的尝试。
- [ ] 默认外部尝试次数 1，不对 POST 透明重试；限制单任务调用数与字节数。取消停止本地等待并尽可能调用远端取消；远端不支持时记录“远端可能继续且仍可能计费”。
- [ ] provider 输出先按不可信文件校验类型、大小和像素，再导入私有制品目录；错误信息、上游回包和 URL 中的密钥均脱敏。

**代表性契约测试：** 在 `test_enhancement_workflow.py` 定义 `test_resume_rejects_stale_input_request`：创建人工等待任务→读取 inputRequestId/version→成功恢复一次→再次提交旧 version，断言 409、队列仅增加一个执行项、原尝试记录不变。在 `test_provider_safety.py` 定义 `test_unknown_provider_result_is_not_resent_after_restart`：替身接收请求后断开→重建服务→读取同任务，断言 PROVIDER_RESULT_UNKNOWN 且调用计数仍为 1。两者分别验证并发恢复与副作用恢复，不能以纯页面快照替代。

**验证：**

```powershell
npm run test:backend -- src/service/test_enhancement_service.py tests/test_enhancement_workflow.py tests/test_provider_safety.py -q
npm run api:generate
npm run test:e2e -- --grep enhancement
npm run verify
npm run check:handoff -- P10
```

真实云调用单独执行，必须有指定测试账户、合法样本、已确认的调用预算；常规 CI 仅运行替身契约测试。交接同时记录 manual_verified、provider_contract_verified、provider_live_verified 三类结果，不能合并为一个“增强已通过”。

**通过条件：** 手动清洗/超分导入与真实本地融合均闭环；人工等待可恢复；无任意命令入口、重复付费或密钥泄漏。没有凭据时，远程适配的状态为 disabled/unavailable，原因可见。

**输出 → P11：** 已验证的人工输入状态机、增强页面、provider 安全契约与逐项验证状态、P10 交接。建议提交：`feat: add manual enhancement and guarded provider adapters`。

## P11：实验性局部移植工作流

**输入：** P10 人工等待/恢复、P07 原坐标和贴回语义、P01 X01 样本与 transplant 命令清单。

**创建/修改文件：**

- `G:/project/RepairAiImage/backend/src/core/transplant_models.py`
- `G:/project/RepairAiImage/backend/src/service/transplant_service.py`
- `G:/project/RepairAiImage/backend/src/infra/transplant_adapter.py`
- `G:/project/RepairAiImage/backend/tests/test_transplant_workflow.py`
- `G:/project/RepairAiImage/frontend/src/modules/repair-workbench/components/transplant-form.tsx`、`keypoint-editor.tsx`、`candidate-review-panel.tsx`
- `G:/project/RepairAiImage/frontend/tests/e2e/transplant.spec.ts`
- `G:/project/RepairAiImage/docs/TRANSPLANT_GUIDE.md`、`docs/handoffs/P11.md`、`P11.json`

### P11.1 冻结移植数据与分步操作

- [ ] 确认固定上游版本的 grid→prep→人工候选导入→finish 的真实输入/输出；记录同侧产品照片、场景、配对点、部件与候选图的要求，不假设任意角度自动适配。
- [ ] 先定义各步 artifact schema：sceneId/productId、原图尺寸、成对关键点、部件名、prepVersion、candidateIds、上游版本；通过同一个 task 的 stage 推进，不另造独立后台流程引擎。
- [ ] 关键点编辑使用原图坐标；拖动/缩放仅改变显示变换。后端拒绝越界、缺少配对、重复点、非有限值；对上游要求的点数和退化几何给出明确校验错误。
- [ ] prep 输出网格/裁切和人工操作说明，转 waiting_input，释放槽；导入候选时验证它绑定同一个 prepVersion。服务端不解析客户端提供的绝对路径。
- [ ] finish 前让用户选择候选并确认；结果页面标明“实验性”，展示贴合/边界/遮挡/颜色/几何检查项。下载不等于人工判定通过，另记录 reviewed、reviewDecision 和 reviewer。
- [ ] 本阶段不增加自动付费生成候选；可复用已授权的 provider 能力时也必须经过 P10 相同的发送确认与预算限制。

### P11.2 验证实验能力并形成可交付状态

- [ ] 先测关键点非法、候选属于其他用户/旧 prep、重复 finish、等待期间取消、重启恢复；任何一步失败保留已完成的非敏感诊断制品。
- [ ] 用 X01 跑真实 grid/prep/finish，保存各阶段实际命令和哈希、输入候选来源、输出与人工审核记录。人工审核不能只填“成功”，必须逐项给出观察与已知缺陷。
- [ ] 若固定版本无法在已声明环境完成 X01，记录最小复现与错误，将 transplant capability 设为 unavailable/experimental，并从可执行操作中禁用；不能用图片替身宣称算法成功。此时只验收禁用行为与故障说明，真实移植验收仍未通过。
- [ ] 更新 SPEC 的能力矩阵和用户指南，明确实验移植是否纳入当前发布范围；M2 核心发布不依赖它，M3 报告必须列出它的实际状态。

**验证：**

```powershell
npm run test:backend -- tests/test_transplant_workflow.py -q
npm run api:generate
npm run test:e2e -- --grep transplant
npm run verify
npm run check:handoff -- P11
```

**通过条件：** 可用时，X01 真实工作流与人工审查完整；不可用时，复现证据、能力禁用与范围说明完整。两种结果必须在交接中区分，后者不算真实算法验收通过。

**输出 → P12：** 实验移植交付状态、样本/审核/故障证据、完整 capability 矩阵、可打包版本和 P11 交接。建议提交：`feat: add experimental transplant workflow and review`。

## P12：Windows 本地部署、离线包与目标机验收（M3）

**输入：** P11 的完整发布范围、P01 上游及模型来源/许可/性能记录、P02 锁文件与质量门禁、P03 配置身份、P08 数据清理、P09 评估回归集。

**创建/修改文件：**

- `G:/project/RepairAiImage/deploy/windows/Build-Package.ps1`、`Install-RepairAiImage.ps1`、`Start-RepairAiImage.ps1`、`Stop-RepairAiImage.ps1`
- `G:/project/RepairAiImage/deploy/windows/Backup-RepairAiImage.ps1`、`Restore-RepairAiImage.ps1`、`Test-Deployment.ps1`
- `G:/project/RepairAiImage/deploy/windows/Initialize-Credentials.ps1`、`deploy.bat`、`start.bat`
- `G:/project/RepairAiImage/backend/tests/test_release_assets.py`
- `G:/project/RepairAiImage/deploy/windows/tests/Deployment.Tests.ps1`
- `G:/project/RepairAiImage/docs/LOCAL_DEPLOYMENT.md`、`OFFLINE_PACKAGE.md`、`UPGRADE_ROLLBACK.md`、`RELEASE_ACCEPTANCE.md`
- `G:/project/RepairAiImage/docs/handoffs/P12.md`、`P12.json`

### P12.1 定义可独立转移的发布包

- [ ] 固定目标 Windows x64 版本、Python 可分发运行时及其授权、OpenCV/NumPy 等 wheel 平台；P01 验证结果决定最终兼容表。不能把开发机已有 Python/Node/CUDA 当目标机前提。
- [ ] 在线构建机执行 npm ci、锁定依赖安装、完整验证；打包生产前端静态文件、后端、固定上游源码/模型、兼容运行时和离线 wheelhouse。构建阶段联网记录与目标机零联网要求分开。
- [ ] 不复制含绝对路径的开发 .venv；安装器使用包内 Python 与离线 wheels 建立目标路径运行环境。若选用便携运行时，其 pip/venv 支持与原生扩展加载必须实际验证；只接受有实测证据的运行时布局。
- [ ] 包内 `package-manifest.json` 记录应用/上游版本、Python 与 wheel 标签、模型/文件 SHA-256、配置版本、许可证清单与构建环境；它只包含非敏感清单，不存凭据。
- [ ] 包含完整运行依赖、模型和许可证；排除 node_modules、开发缓存、.env、用户数据、私密测试图与凭据。前端已构建，目标机不需要 Node/npm；不依赖源项目旁边的其他目录。
- [ ] 安装时使用包内解释器和 `--no-index --find-links` 离线安装，禁用自动更新/下载；不用上游可能首次联网的启动器作为生产入口。安装器发现缺件/哈希错即失败，不能转为在线补下载。
- [ ] 默认单实例/单后端进程，沿用仓储独占锁和受限任务池。生产 3000 端口由后端提供静态页面及同源 API；8000 仅为开发后端端口，不在生产重复暴露第二套 API。

发布包计划布局：

```text
RepairAiImage-windows-x64.zip
  app/                    后端、前端 dist、固定 vendor 源码与模型
  runtime/                已验证的 Python 运行时、必要本地动态库
  wheelhouse/             带哈希锁和目标平台 wheel 的离线依赖
  deploy/                 安装、启动、停止、凭据初始化、备份/恢复/验收脚本
  licenses/               应用、上游、模型、运行时与依赖许可
  config.example.yaml     无密钥模板
  package-manifest.json   非敏感版本和哈希清单
  deploy.bat
  start.bat
```

### P12.2 安装、身份和启动脚本

- [ ] 默认安装目录 `C:/RepairAiImage`，独立数据根 `C:/ProgramData/RepairAiImage`；实际路径由安装参数覆盖。数据根包含 uploads/tasks/artifacts/evaluations/logs/credentials，不在应用覆盖范围。
- [ ] 安装器先验证包清单、系统兼容、可写空间、端口和既有数据 schema；不兼容立即中止。已有安装必须先停止和备份，再应用更新。
- [ ] 首次身份初始化用交互式安全输入或受限凭据源生成账号与密码哈希；拒绝默认弱密码，不把密码写进命令行、日志或示例。限制凭据/数据目录 ACL。
- [ ] 默认绑定 127.0.0.1:3000；启动后浏览器通过真实 HTTP Basic 身份访问。共享到局域网时，增加受信任 HTTPS 入口、证书与绑定配置并重新验收；不得把 loopback 的 HTTP 部署条件扩展到公网。
- [ ] 启动脚本校验模型、配置、身份和仓储锁，启动后记录 PID 与创建时间；停止脚本按实际身份停止对应进程树。不能仅用 PID 或进程名停止其他应用。
- [ ] 前台 start.bat 保留有用的错误输出，Ctrl+C 触发优雅停止；启动失败不能闪退隐藏原因。后台辅助进程在 Windows 使用隐藏窗口，避免反复弹出控制台。
- [ ] 本期验收为可重复安装和启动的本地应用；如后续要求 Windows 服务，再增加 SCM/WinSW 安装、自动恢复与提权测试任务。当前不将脚本启动描述为已注册 services.msc 服务。

计划中的目标机操作示例（下列脚本在本阶段实现后才执行）：

```powershell
# 1. 解压后的包目录；只包含已验证的离线发布物
Set-Location -LiteralPath 'C:/RepairAiImagePackage'

# 2. 安装器参数为本阶段冻结的脚本契约
& './deploy/Install-RepairAiImage.ps1' -InstallDir 'C:/RepairAiImage' -DataDir 'C:/ProgramData/RepairAiImage'

# 3. 首次交互创建本地管理员，不在命令行传明文密码
& 'C:/RepairAiImage/deploy/Initialize-Credentials.ps1' -DataDir 'C:/ProgramData/RepairAiImage'

# 4. 先在一个终端前台运行
& 'C:/RepairAiImage/deploy/Start-RepairAiImage.ps1' -InstallDir 'C:/RepairAiImage' -DataDir 'C:/ProgramData/RepairAiImage'
```

在第二个终端运行部署验收；身份由脚本交互读取，报告目录不含密码：

```powershell
& 'C:/RepairAiImage/deploy/Test-Deployment.ps1' -BaseUrl 'http://127.0.0.1:3000' -DataDir 'C:/ProgramData/RepairAiImage' -EvidenceDir 'C:/RepairAiImageAcceptance'
```

### P12.3 用真实目标环境证明部署成立

- [ ] 先写安装脚本测试：路径含中文/空格、无写权限、3000 被占用、缺模型/损坏 wheel、重复安装、锁已占用、已有数据版本过新、失败后的状态可诊断。
- [ ] 干净解压后断网安装与启动；记录 OS/CPU/RAM/运行时/版本/网络条件。基础 ONNX 路径不得请求云 API，且没有“缺包时静默在线安装”。
- [ ] healthz 只反映进程健康，readyz 验证配置、存储和必需基础依赖；响应不泄漏路径/凭据。可选云 provider 关闭不阻断基础 readyz，capabilities 给出独立原因。
- [ ] 在目标机通过受保护页面登录→上传 D01→真实修复→SSE→比较→下载→评估报告，核对模型/输出哈希；补测 401/403/404、取消、等待恢复、重启恢复和清理引用保护。
- [ ] 相机/大图/无效参考/全跳过/批量部分失败回归，结果与 P01/P09 声明一致；记录真实耗时和资源峰值，不把开发机构建成功当目标机性能验收。
- [ ] 若首次接入的云服务或额外模型没有真实验收条件，保持禁用并记录原因，不要求它们阻塞已完成的基础离线能力发布。
- [ ] 输出可追溯的安装日志、API 状态码、进程/端口、真实任务/模型哈希、评估报告和界面证据；自动脱敏，合法样本在安全证据目录保存。
- [ ] 对真实部署入口记录安全响应头、强制 CSP 与 HTTPS/HSTS 的适用结果；验证页面允许的脚本/样式/SSE/图片资源正常，违规资源被阻止。按 P00 场景复验性能预算与键盘操作；性能报告标明实测环境、样本量和实验室/真实用户口径，未达到门槛时不得直接标记 accepted。

### P12.4 备份、升级与完整回退

- [ ] 停止应用并确认没有写入/子进程后，同时备份应用目录与独立数据根；生成带版本/哈希的备份清单，验证可读后才继续。
- [ ] 安装器仅替换发布清单内的应用文件，不覆盖已有凭据、业务 YAML 和用户数据。升级前检查 schema 兼容；首版不做未声明的数据结构自动转换。
- [ ] 升级后执行真实登录、历史任务/制品读取、新建修复和 readyz 检查；失败立即停止，不继续接受写请求。
- [ ] 回退必须在停机状态恢复同一备份时点的应用、配置与数据，不能只退源码。恢复脚本验证目标绝对路径属于明确安装/数据目录；拒绝盘符根与外部路径，不拼接跨 shell 删除命令。
- [ ] 在验收环境实际演练“旧版有任务→备份→升级失败→恢复→旧任务和下载仍可用”；记录恢复时长与丢失窗口。涉及覆盖现有业务数据的恢复，执行前单独确认目标和备份时间。

构建机门禁与打包命令：

```powershell
Set-Location -LiteralPath 'G:/project/RepairAiImage'
npm run verify
npm run test:backend -- tests/test_release_assets.py -q
Invoke-Pester -Path './deploy/windows/tests/Deployment.Tests.ps1' -CI
& './deploy/windows/Build-Package.ps1' -OutputDir './release'
npm run check:handoff -- P12
```

交接检查命令在目标验收、备份与恢复证据已汇入清单后才能通过；仅执行上述构建机命令不等于 P12 accepted。测试报告使用固定工具版本，Pester 的取得在构建环境准备时完成，目标机安装不依赖在线安装测试工具。

**通过条件：** 可独立转移离线包；干净目标机离线安装、真实基础任务和恢复演练通过；凭据和数据保留正确；所有发布功能的验收状态与页面一致。云/实验能力的未通过项有准确禁用状态，不能列入已验证能力。

**最终输出：** M3 发布包与 SHA-256、配置/部署/升级/回退文档、目标机实际验收报告、真实能力矩阵和 P12 交接。建议提交：`build: package offline Windows runtime and deployment checks`。

## 6. 阶段输入输出总表

下面每行输出均包含对应的 `docs/handoffs/PXX.md` 和 JSON；下一行通过该入口取得实际文件和验证证据，不能仅凭“上一阶段完成”的口头结论继续。

| 阶段 | 直接输入 | 主要实物输出 | 下一阶段依赖的确定条件 |
| --- | --- | --- | --- |
| P00 | 用户需求、项目内两份 L0 标准及哈希基线、当前方案 | SPEC/架构映射/API/验收矩阵/标准哈希 | 范围、身份、接口与标准约束冻结 |
| P01 | P00 契约 | 固定上游/许可/模型哈希/合法样本/真实运行基线 | 核心命令及模型路径真实可复验 |
| P02 | P01 基线 | 工程/锁文件/根脚本/CI/分层与交接门禁 | 可安装、可启动、现有检查通过 |
| P03 | P02 工程 | fail-closed 配置、真实身份、私有上传/制品 | 身份/越权/文件边界契约通过 |
| P04 | P03 身份文件底座 | 任务/队列/真实适配/取消/恢复/SSE | 状态持久且进程生命周期可验证 |
| P05 | P04 API 与状态 | Token/模板/Storybook/SWR/SSE/视觉基线 | 前端公共能力及鉴权门禁通过 |
| P06 | P05 公共能力与 P04 引擎 | 基础修复真实端到端 M1 | 用户真实上传到下载全链路通过 |
| P07 | P06 M1 | 校色/链式/贴回及边界样本 | source、顺序、坐标语义可复验 |
| P08 | P07 模式与任务样本 | 任务中心/系统诊断/安全清理 | 管理动作与后端权威状态一致 |
| P09 | P08 管理闭环 | 批量/指标/报告/核心版本 M2 | 配对、统计、导出与真实任务对账 |
| P10 | P09 M2 | 人工增强/可选 provider/副作用安全 | 人工流程真实通过，外部能力分项标记 |
| P11 | P10 人工流程 | 实验移植/人工审核/可用或禁用证据 | 真实能力范围明确，失败不得伪装成功 |
| P12 | P11 发布范围 | 离线发布包/真实部署与恢复报告/M3 | 干净目标机验证完成、数据保留正确 |

## 7. 标准与能力覆盖检查表

| 要求 | 首次落地 | 最终证明 |
| --- | --- | --- |
| 两份 L0 标准、后端分层、前端模块依赖 | P00/P02 | 架构文档、故意违约 fixture、CI 检查 |
| 唯一 Ant/Pro 体系、Token/页面模板 | P05 | Storybook、生产页面、视觉报告 |
| Router Data Mode/SWR 单一服务端状态/OpenAPI 类型 | P02/P05 | 类型漂移检查、组件/E2E、无第二缓存 |
| 真实身份、角色、文件/任务隔离、密钥保护 | P03 | 拒绝路径、跨用户访问、生产入口验收 |
| 安全响应头、CSP 强制效果、凭据轮换生效点 | P03/P12 | 真实响应、资源允许/拒绝、重载/重启测试 |
| 性能预算、键盘操作与可访问状态 | P00/P05 | 固定环境报告、真实页面及目标入口复验 |
| 上游固定版本、模型许可/哈希、真实推理与降级区分 | P01/P04 | 真实样本、执行记录、目标机任务 |
| 取消、并发、幂等、重启恢复、SSE | P04 | OS 进程树、重启故障、状态/事件测试 |
| 迷宫纹/校色/链式/贴回 | P06/P07 | 合法样本、原始输出/参数/比较图 |
| 任务中心/诊断/引用安全与保留 | P08 | API/E2E、清理中断与恢复证据 |
| 评估数据配对/指标定义/CSV 安全 | P09 | 独立数值核对、子任务对账、报告 |
| 人工增强/外部服务消费不确定性 | P10 | 真实手动流程、替身故障测试、可选真实云验证 |
| 实验移植的人工审核与能力禁用 | P11 | X01 或明确复现失败与禁用证据 |
| 本地离线运行/数据保留/备份回退 | P12 | 干净目标机断网安装、真实任务与恢复演练 |

## 8. 每阶段统一执行方式与失败回流

1. 只读检查前一交接的 accepted、产物哈希和能力限制；P00 从用户需求与 L0 开始。P02 起使用交接检查器执行机器校验。
2. 把该阶段小节拆为单次可审查的修改，先写能发现实际风险的失败用例，再实现最小变更，运行该小节的定向检查；不为文案/Token 的低风险微调编写镜像实现测试。
3. 小节通过后检查差异与敏感信息，再提交 Conventional Commit；提交仅包含本阶段相关文件。根 npm test 全绿才可进入提 PR 流程，PR 不是本计划默认执行动作。
4. 阶段末运行列出的适用门禁，把实际命令、退出码和报告写入 evidence；更新 API 时同步生成类型、兼容说明和消费者。
5. 创建输出清单和 SHA-256，更新交接。不得先写 accepted 再补测试；下游只消费已验收文件。
6. 当前失败在当前阶段修复；若根因是上游行为/接口/标准改变，退回最早受影响阶段更新 ADR/契约/样本，重验依赖链；保留旧证据并标注 superseded，不覆盖历史结论。
7. 缺少真实模型、目标机或 provider 条件时，记录该能力 pending/unavailable 与确切缺口；可选能力按既定发布范围禁用，必需能力未验收则不能发布。不得把单测替身、前端截图或 healthz 当真实算法/部署证明。
8. 数据安全相关故障停止写入并保留诊断，按已验证备份恢复；不绕开幂等、权限、凭据、锁文件或 migrations 红线“临时跑通”。

## 9. 首次实施入口与计划维护

后续获准实施时从 P00 开始，不直接搭页面：先落地需求/标准/API/验收矩阵，再交付 P00 交接，随后 P01 固定并实测上游。P01 的实际运行结果决定资源上限、兼容版本和可启用功能；如与当前假设不同，先更新本文受影响部分并记录原因。

本文是分阶段工作计划，不包含已完成实施或已验证部署的声明。当前文档产物为本文及 docs/standards/ 下两份标准副本，已完成复制一致性校验与计划引用更新；P00–P12 尚未执行，没有安装依赖、拉取上游、编写应用、运行应用测试、启动服务或部署。阶段人力与日历排期在 P01 得到真实样本、性能和能力缺口后估算，避免以未测环境给出确定交付日期。
