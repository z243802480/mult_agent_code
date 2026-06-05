# Reference Briefs（对标学习）

每个 Vibe Slice 开工前必须阅读并填写对应 brief（半页即可）。

## 四步 workflow

1. **Read（30min）** — OpenCode / Claude Code docs / [codex-rs](https://github.com/openai/codex) 相关目录
2. **Map（15min）** — 填写 brief：`observed_pattern` → `asteria_file` → `do_not_copy`
3. **Vibe（90min）** — Red → 最小 diff → Green → 5min demo
4. **Record（10min）** — brief 底部记录实现 commit / 偏差

## 模板

```markdown
# Slice Sn — 标题

## observed_pattern（行业已验证）
- ...

## asteria_mapping（我们怎么做）
- 文件：
- 行为：

## do_not_copy（禁止照搬）
- ...

## 实现记录
- date:
- notes:
```

## 可选 research 命令（仅服务当前 slice）

```bash
python -m asteria_runtime research --type competitive_research --query "..." --root .
python -m asteria_runtime research --type open_source_research --query "..." --root .
```

机制摘要已并入 [研发总计划 §5](../../docs/zh/研发总计划.md)。
