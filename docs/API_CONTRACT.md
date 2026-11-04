# HTTP API 契约基线

状态：P00；与 `docs/superpowers/plans/2026-11-04-repair-ai-image-implementation-plan.md` §5.1–5.4 对齐。传输 TLS、鉴权、owner 过滤和权限均由服务端强制；API 未实现、未由 OpenAPI/契约测试验证。

## 通用格式

JSON 成功：`{"code":0,"msg":"ok","data":{...}}`。JSON 错误：`{"error_code":"UPPER_SNAKE_CASE","message":"安全消息","trace_id":"..."}`。非 JSON 的文件下载/SSE 保留对应 Content-Type，以响应头/事件携带 trace。认证使用命名用户 Basic；body 禁止 ownerId 与物理路径。所有资源访问先鉴权再按身份裁决。

## 端点目录

| 方法/路径 | 成功语义 | 权限/关键约束 |
|---|---|---|
| GET `/api/v1/session` | 当前主体、角色、认证方式 | 已认证；不返回凭据 |
| GET `/api/v1/capabilities` | 模式 availability/reason、参数范围、模型/上游版本、降级标识 | 已认证 |
| POST `/api/v1/uploads` | multipart 暂存文件，返回 uploadId/尺寸/哈希/过期时间 | operator；类型、像素、大小限制由配置白名单决定 |
| DELETE `/api/v1/uploads/{uploadId}` | 删除未引用暂存文件 | 所有者；已引用则 409 |
| POST `/api/v1/tasks` | 返回 202 与 taskId | operator；同用户 Idempotency-Key + 请求哈希持久绑定 |
| GET `/api/v1/tasks` | 分页任务列表 | 角色数据范围；过滤/游标由实现 OpenAPI 固化 |
| GET `/api/v1/tasks/{taskId}` | 任务详情、状态/阶段/进度/输入/产物引用 | 所有者或 admin；越权资源返回 404 |
| POST `/api/v1/tasks/{taskId}/cancel` | 请求取消 | operator；幂等；进程树终止前状态为 canceling |
| POST `/api/v1/tasks/{taskId}/retry` | 创建新 taskId 并含 retryOf | operator；不得隐式重复写 |
| POST `/api/v1/tasks/{taskId}/resume` | 人工输入后恢复 | operator；inputRequestId + version，重复/过期受控 |
| GET `/api/v1/tasks/{taskId}/events` | 认证 SSE，快照后递增事件 | 同任务权限；支持 Last-Event-ID/reset；断流不取消 |
| GET `/api/v1/tasks/{taskId}/artifacts` | 制品角色/格式/大小/期限 | 同任务权限 |
| GET `/api/v1/tasks/{taskId}/artifacts/{artifactId}` | 预览/下载 | 同任务权限；无物理路径参数 |
| GET `/api/v1/tasks/{taskId}/logs?cursor=...` | 脱敏分页诊断 | admin；cursor 分页、大小上限 |
| DELETE `/api/v1/tasks/{taskId}` | 清理终态任务与私有文件 | admin；引用存在返回 409；审计 |
| POST `/api/v1/evaluations` | 创建评估及子任务 | operator；配对/请求幂等规则 P09 冻结 |
| GET `/api/v1/evaluations/{evaluationId}` | 评估进度、子任务和结果 | 所有者/admin |
| POST `/api/v1/evaluations/{evaluationId}/cancel` | 取消评估和未完成子任务 | operator；幂等 |
| GET `/api/v1/evaluations/{evaluationId}/reports/{format}` | CSV/JSON 报告 | 授权；format 枚举、审计、大小上限 |
| DELETE `/api/v1/evaluations/{evaluationId}` | 删除终态评估 | admin；计划 P09 增加；引用/审计策略同步 OpenAPI |
| GET `/api/v1/system/status` | 脱敏依赖、模型、存储、provider 状态 | admin |
| GET `/healthz`、`/readyz` | liveness/readiness | 仅公开批准摘要；存活恒 200，就绪缺必需依赖 503 |

## DTO 与输入规则

上传结果字段：`uploadId`、`width`、`height`、`format`、`sizeBytes`、`sha256`、`expiresAt`。创建任务输入：`mode`、`inputs: [{role, uploadId, sequence?}]`、模式参数；响应含 `taskId`、`status=queued`、`version`。`ownerId` 只由认证主体生成。输入 role 枚举：`input/source/edit/chain_step/mask/ground_truth/washed/upscaled/scene/product/keypoints/candidate`；模式约束允许的角色和数量，链式依据显式 sequence 排序。暂存上传在创建任务时校验归属并一次性绑定；缺失/过期不得入队。

任务 DTO 至少含 `taskId, ownerId(仅内部/按权限投影), mode, status, stage, progress, version, createdAt, updatedAt, inputs, artifacts, retryOf, errorCode, traceId`。对非所有者响应不得泄露 owner 或资源存在性。人工等待仍为 `running`，并带 `stage=waiting_input`、`inputRequest`；不引入额外生命周期状态。

## 状态、错误和幂等

状态：`queued/running/succeeded/failed/canceling/canceled`。迁移：queued→running/canceled；running→succeeded/failed/canceling；canceling→canceled（确认整个进程树终止后）。终态不可重开；重试新 ID；版本冲突 409。Item 独立状态 `pending/running/succeeded/skipped/failed/canceled`；全 skipped 展示“未处理”，不可计修复成功；部分失败任务为 failed 并保留成功产物。重启保留 queued/waiting_input；确认无孤儿后将运行中任务标 `failed/WORKER_INTERRUPTED`。外部结果未知 `PROVIDER_RESULT_UNKNOWN`，不自动重试或重复付费。

错误映射：400 参数/模式/配对/图像非法；401 未认证；403 已知资源禁止（一般资源越权可用 404）；404 不存在或隔离资源；409 状态/版本/引用/幂等冲突；413 超限；415 类型不支持；422 字段校验；429 限流且含 Retry-After；503 必需依赖缺失；500 仅安全消息和 trace_id。429/503 对创建、恢复、付费操作禁止自动重试。

同一用户、同一 Idempotency-Key 和相同规范化请求哈希返回同一结果；不同哈希返回 409。键与结果持久化，防重启重放。providerAttemptId 持久化；超时不代表未消费。

## SSE 与安全

事件含单调递增 `id`、`event`、`data` 和 trace；订阅先快照再增量，Last-Event-ID 越过保留窗口则 reset/snapshot。关闭连接不改变任务状态。所有写请求验证 Origin/同源策略；不允许宽松凭据 CORS。生产非 loopback 强制 HTTPS。SSE 与下载须实测 Basic 凭据传递。Health 仅暴露最小状态，不含路径、凭据或敏感依赖细节。
