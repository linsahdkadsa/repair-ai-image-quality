# P02 技术栈与兼容基线

核验日期：2026-11-04。版本固定于 npm 工作区清单、`package-lock.json` 与 `backend/requirements.lock`；只有干净安装和实际构建通过后，才视为已验证组合。

| 层 | 固定基线 | 依据/限制 |
| --- | --- | --- |
| Node/npm | Node 22.22.2 / npm 11.6.2 | Node 22 LTS；npm 11.6.2 可稳定解析当前 Vitest 可选 peer 依赖，npm 10.9.x 在此依赖图触发 Arborist 异常 |
| Python | CPython 3.12.10 | P01 已测环境；`backend/.venv` 独立，锁文件含 SHA-256 |
| API | FastAPI 0.162.0、Uvicorn 0.54.0 | 仅提供存活/就绪探针和 OpenAPI 起点，不包含业务 API |
| 前端 | React 19.3.1、TypeScript 5.9.3、Vite 7.3.7 | React 插件 peer 约束拒绝 Vite 8；Vite 7.3.7 修复审计中的高危问题 |
| UI 与路由 | Ant Design 5.29.3、React Router 7.18.5 | ProComponents 在 P02 未被骨架使用，暂缓加入安装集；当前可用版本的传递依赖触发高危审计，P05 采用前必须重新验证安全版本 |
| 服务端状态/API | SWR 2.3.6、Axios 1.21.0、ECharts 6.1.0 | 单一 SWR 缓存；无业务请求在 P02；固定版本已修复当前审计告警 |
| 测试/组件 | pytest 9.2.0、httpx2 2.16.0、Vitest 4.1.12、Testing Library 16.3.0、Storybook 10.6.5 | Starlette TestClient 使用 httpx2 避免弃用警告；前端单元/骨架测试与静态 Storybook 构建；E2E/视觉留待 P05 |
| API 类型 | openapi-typescript 7.13.0 | 从 FastAPI OpenAPI 生成；`npm run api:check` 比较生成结果 |

ProComponents 暂缓到 P05：P02 骨架不消费该组件，而候选版本当前引入高危 `path-to-regexp` 依赖，npm override 未能可靠更新嵌套锁定项。P05 纳入前须重新选择并通过审计。P01 的 GPT Maze ONNX 权重未确认再分发授权。P02 不将它加入任何依赖、打包配置或新建发布物；该能力仍为 blocked/pending。上游固定副本仅作来源审查，P02 不修改其内容。YuNet 如未来分发须保留 MIT 声明。

本阶段未引入 CI 密钥、云 provider、数据库或迁移。E2E、视觉回归和部署检查显式返回未实现错误，不可被误报为通过。
