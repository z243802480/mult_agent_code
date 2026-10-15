# S96 权限卡确认后状态归一（2026-10-15）

## 真实证据与复现

S93 的原始 Studio 会话里，三张 `permission_request/waiting_user` 均有匹配的 `resolved_job_id`。服务端回放已按 job 过滤已解决的卡，所以刷新后正常；当前页面的 `mergeEventLists` 却只增不减，SSE 送来解决标记后仍保留旧卡。定向 Red 测试复现：合并旧请求与解决事件后，返回列表仍含已批准 job 的请求。

另外，权限接口在 HTTP 200 下可返回 `{ok:false}`；旧 `api.permitJob` 未检查它，`useSessionEvents.permitJob` 吞掉异常，`PermissionCard` 因调用返回而显示“已确认/已取消”。定向 Red 测试证实缺失 job 的拒绝响应被当成功。

## 修复

- live 事件合并按 `resolved_job_id` 清除对应 job 的旧 `permission_request`；另一个待处理 job 保留。标记与原请求仍在 JSONL 审计账本里。
- `api.permitJob` 只接受服务端 `ok:true`；hook 报错并让卡片保持可重试。成功后主动刷新事件，SSE 延迟时也能清掉旧卡，并给出已记录批准/已取消提示。
- 服务端重复拒绝或拒绝不存在 job 改为 `{ok:false}`，不再谎报取消成功。

## 验收与边界

- live merge Red→Green：已解决卡消失，未解决卡保留，旧事件迟到也不复活；接口 `{ok:false}` Red→Green。
- 真 Studio 浏览器用户路径：显式 `run` + `ask_everything` 出现 1 张“待批准”卡，点击取消后当前页面 0 张、无“待批准”，刷新后仍为 0。首次浏览器尝试载入旧 `dist`，旧卡仅在刷新后消失；执行 `npm run build` 后复跑才得到上述 live 结果。取消路径未启动运行时任务。
- `user-thread-copy-smoke` 走真实 BFF：拒绝一张卡后回放过滤该卡、保留另一张；重复拒绝返回失败。批准路径与拒绝路径使用同一个 `resolved_job_id` 投影，但本次浏览器实测仅覆盖取消，不把它写成批准端到端已跑。
- 没有改 Runtime 权限政策或原始审计记录。原 S93 临时会话仅只读核对；新增浏览器验收会话位于该临时工作区，未纳入仓库。
- 本地门禁：Studio Vitest 45 文件、269 测试通过；41 项 hermetic smoke 全部通过（4 项真实模型 gate 因未提供 key 保持 SKIP）；`npm run build`、`npm run typecheck`、`npm run lint`（0 error，47 条既有 warning）、文档契约 23 项通过。首次将全量单测与全量 smoke 并行运行时，跨进程 I/O 单测触及 5 秒默认时限，replay smoke 遇一次连接重置；串行复跑上述门禁均通过，故未改该测试的默认时限。
