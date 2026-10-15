# S95 Studio 事件账本完整性（2026-10-15）

## 触发与定位

S94 真模型运行完成，但 Studio 主线程显示一段 `rovider_call_seconds` 起头的内部事件元数据。原始 Runtime `user_progress.jsonl` 可解析；Studio 会话 `events.jsonl` 有 2150 个物理行，其中第 1129 行为截断 JSON。原读取逻辑在解析失败时构造 `raw.content_delta`，直接把文件残片交给主线程。相邻 Node 事件序号有乱序。Node 事件总线和 Python 模型 sink 同时追加这个文件，而 Node 的多路 `appendEvent` 缺少串行化。

## 改动

- Node 事件总线按会话排队追加，让序号分配、落盘和 SSE 发出保持同序；失败不会永久卡住后续队列。
- Python 模型 sink 把每条 JSONL 编码为单个字节串，以一次 OS 追加写入，避免文本缓冲分段写入；仍保留原来的 best-effort 边界。
- Studio 回放解析遇到损坏行直接跳过，保持有效行的物理行序号，不再把任意存储字节当正文。

## 验收

- 定向测试：200 条 Node 并发追加按 `seq=0..199` 落盘；Node 与真实 Python sink 各 100 条并发写入后，200 行全部可解析；坏行前后事件可读，损坏元数据不在返回值中。
- S94 原始会话保留原文件未改：2150 个物理行、2149 个有效事件，损坏行被隔离。Studio 浏览器回放中不再显示 `rovider_call_seconds` / `runtime_user_progress` 残片，仍显示版本 `0.1.0` 和“已验证”。
- Studio Vitest 265/265、hermetic smoke 41/41（本机以 `PYTHONPATH=F:\mult_agent_code\src` 运行）、Python `test_http_transport.py` 4/4、文档契约 23/23、Studio typecheck 通过。仓库本机的 Prettier 全量检查因 Windows 工作树行尾把 219 个既有文件标为需格式化；改动文件单独检查通过，未全仓重排。ESLint 0 error，47 个既有 warning。

## 边界

跨进程测试覆盖了本机一次 100+100 并发追加，尚不能证明所有平台、所有异常中断下 JSONL 永不损坏。读取端会隔离坏行，但坏行承载的事件无法恢复。若再观察到跨进程损坏，应改为单写者汇流。S93 的已确认权限卡残留留作下一刀独立复现。
