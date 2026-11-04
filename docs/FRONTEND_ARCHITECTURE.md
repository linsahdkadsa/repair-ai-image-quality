# 前端架构基线

状态：P00 文档基线；尚无 UI 或视觉验收。

## 技术与模块边界

按 L0 采用 Vite、React、TypeScript strict、Ant Design + ProComponents（唯一组件体系）、React Router Data Mode、SWR（唯一服务端缓存）、Axios、CSS Modules、ECharts、Day.js；Storybook、Vitest/RTL、Playwright。版本在 P02 根据兼容矩阵锁定。函数组件；React 组件导出名 PascalCase，文件名 kebab-case（见 ADR-0001）。不另加 TanStack Query、第二套后台组件库或服务端状态容器。

```text
frontend/src/
  app/          路由、鉴权外壳、错误边界、主题、应用装配
  pages/        workbench、tasks、evaluations、system 页面
  features/     各业务模块的组件、hooks、API 调用与页面局部样式
  shared/       API client、SWR 配置、设计 Token、通用组件与工具
```

允许依赖：`app → pages → features → shared`；同层 feature 不互相导入内部实现。页面不直接拼 URL；API client 统一处理认证错误、trace_id、错误 envelope 和下载/SSE 特殊响应。服务端状态仅经 SWR；临时拖拽位置等短暂 UI 状态可局部保存，不持久化令牌/业务数据到 localStorage。权限呈现用于 UX，后端始终裁决。

## 路由和页面草图

受认证的 `/workbench`、`/tasks`、`/tasks/:taskId`、`/evaluations`、`/system`；页面菜单可按角色隐藏，但深链 API 必须由后端拒绝越权。默认中文、浅色、主色 `#1677ff`。使用 L0 标准页面模板，加载/空/错误/无权限状态齐备。

```text
工作台: 侧栏 | 模式与参数/上传 | 任务进度 | 输入-结果比较与下载
任务列表:侧栏 | 搜索/状态/模式过滤 | 分页 ProTable | 行操作
任务详情:侧栏 | 状态/阶段 | 输入与参数 | 产物比较 | 事件/诊断
评估:    侧栏 | 数据集/模式/指标选择 | 批次进度 | 结果表/报告
系统:    侧栏 | 依赖、模型、存储与能力状态 | 管理操作（仅授权）
```

1440/1024/768px 验收；在 768px 下单列堆叠、比较面板纵向排列。基础字号 14px；间距 Token 4/8/12/16/24/32px；表格默认 20 条；语义色只从 Ant Design Token 映射。功能按钮键盘可用，比较提供不依赖拖动的并列/切换视图。

## L0 前端追踪

| 来源条款 | 冻结决策 | 验收阶段 |
|---|---|---|
| 前端标准 §1/§2 唯一 Ant+Pro、Vite 模块化、单一服务端数据源 | React + Ant/Pro；SWR 唯一服务端缓存 | P02/P05 静态检查与组件测试 |
| §4 Router Data Mode、SWR、Axios、CSS Modules | 固定采用；版本 P02 锁定 | P02 版本审查、P05 集成 |
| §5 kebab-case 文件名、函数组件与行为约束 | kebab-case 文件，PascalCase 导出 | P02 lint/目录检查 |
| §8 Token/模板/Storybook | 本文 Token 与四页面模板，P05 补 Storybook | P05 Storybook、视觉审查 |
| §10 会话/敏感数据/URL安全 | 不持久化凭据；后端权限权威 | P03/P05 安全测试 |
| §11 LCP/INP/CLS 候选指标 | 按 SPEC 环境和样本规则分别实测 | P05/P12 报告 |
| §12 单元/组件/E2E/视觉门禁 | Vitest/RTL/Playwright，固定视觉环境 | P02/P05/P12 |
| §14 页面完成标准 | 模板、真实接口、权限/错误、键盘/窄屏、视觉及 Storybook | P05/P06 |
