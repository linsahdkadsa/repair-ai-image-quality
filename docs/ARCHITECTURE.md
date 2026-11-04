# 后端与整体架构基线

状态：P00 文档基线；尚无工程代码或运行验证。

## 结构与依赖

```text
infra/bootstrap (唯一组合根：配置、实例锁、依赖装配、启动/关闭)
  └─ api (HTTP/SSE 路由、认证/授权边界、DTO、序列化)
       └─ service (用例编排、事务边界、权限语义、状态转换)
            ├─ repo (接口实现：原子 JSON、私有文件、事件日志)
            └─ core (领域模型、状态机、错误码、协议/端口)
infra adapters ──实现──> core ports
```

允许的依赖方向：`api → service → core`；`repo → core`；`infra → api/service/core` 仅用于装配与适配。`service` 通过 `core` 定义的 repository/engine/identity/clock/process ports 调用实现；`api` 不直接访问 repo 或文件系统；`core` 不依赖 FastAPI、Pydantic、具体存储、进程或上游包。禁止循环依赖及业务模块跨层绕过。阻塞图像处理置于资源受限子进程，生命周期由 infra 执行器管理，service 只依赖协议。

建议目录：`backend/app/{api,service,repo,core,infra}`；单元测试贴近被测模块，HTTP/装配集成测试位于 `backend/tests/`。不得创建/修改 `migrations/`；首版无数据库。

核心端口至少包含 TaskRepository、UploadRepository、EvaluationRepository、EventRepository、ImageEngine、IdentityProvider、ProcessExecutor、Clock。实现注入必须只发生于 bootstrap；接口和 DTO 的序列化边界属于 api，领域状态合法性由 core/service 共同约束。

## 存储、身份和运行边界

首版单实例。安装目录与可配置 data 根分离；data 根通过独占锁防止并发实例。JSON 记录 schemaVersion 和 version，写入同目录临时文件、flush 后原子替换，乐观锁冲突为 409。文件通过私有 ID 引用，不对客户端暴露物理路径。Basic 默认；真实账号来源和凭据加载由 P03 固化，启动缺凭据必须 fail-closed。非 loopback 需 HTTPS。无数据库是因首版单实例本地部署和文件型任务/制品为主，避免当前阶段引入无业务必要的服务和迁移；若并发/查询/一致性基准不满足，须 ADR 评估而不是暗换实现。

## 可观测性与安全

所有请求、事件、任务与上游调用贯穿 trace_id；日志脱敏、不记凭据/图像内容/敏感路径。上游超时结果未知记 `PROVIDER_RESULT_UNKNOWN`，不自动重试或重复付费。健康与就绪分开；对外错误为安全消息。权限由服务端在资源访问时检查，跨用户访问返回不泄露存在性的 404。

## L0 架构约束追踪

| 来源条款 | 项目映射 | 文件/阶段 | 验收 |
|---|---|---|---|
| 通用架构 §1 分层单向、禁止循环 | api→service→core；repo/infra 实现 core ports | 本文、`backend/app/**`；P02/P04 | P02 静态边界检查含故意违约 fixture |
| §2 后端与前端分离、共享包不得穿透 | `backend/` 与 `frontend/` 分离，仅契约/生成类型共享 | P02 | 目录/导入边界检查 |
| §3 类型/文件名遵循语言规范，概念一致 | 后端 Python snake_case；TS 模块 kebab-case，组件 PascalCase 导出；冲突见 ADR | 本文、前端架构；P02 | lint 与路径规则检查 |
| §4 白名单配置、拒绝未知字段、敏感字段拒启动 | YAML+环境变量，安全项仅部署级受控配置 | ADR、`backend/app/infra/config.py`；P03 | 非法配置与缺凭据拒绝启动 |
| §5 分层测试、正常/非法/权限/依赖失败 | unit + 装配/API 集成，外部依赖可控替身 | TEST_PLAN；P02-P04 | CI 测试报告 |
| §6 日志等级、trace、脱敏 | 统一结构日志与 trace_id | `backend/app/infra/logging.py`；P03 | 敏感信息扫描和日志契约 |
| §7 密钥/数据不入库、提交聚焦 | `.env`、状态、制品排除；无 Git 时不提交 | P02/P12 | 敏感文件检查 |
| §8 依赖来源/许可/漏洞治理，警告失败 | 锁版本、依赖审查与 CI 门禁 | P02 | CI 报告 |
| §9 REST/版本化契约、统一 envelope/稳定错误码、healthz/readyz、trace 透传 | JSON envelope；liveness/readiness；校验/生成 trace_id 并贯穿响应、日志、下游与审计 | API_CONTRACT、backend/app/infra/trace.py；P02-P04 | OpenAPI/契约测试验证状态码与头；健康/就绪和 trace 集成测试 |
