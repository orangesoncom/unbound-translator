---
name: unbound-docs-sync
description: Keep Pokemon Unbound translator docs and Codex project metadata aligned. Use when scripts, workflow, JSON shape, ROM assumptions, supported languages, AGENTS.md, README.md, .codex agents/config, or .agents skills change; compact AGENTS.md when it grows.
---

# Unbound Docs Sync

Update both `AGENTS.md` and `README.md` when important workflow, script, output, language, ROM, repository layout, Codex config, subagent, or skill behavior changes.

## Rules

Keep `AGENTS.md` compact. Merge duplicate bullets, remove stale history, and keep durable facts only: script order, ROM assumptions, extraction/menu audit notes, token/control rules, injection assumptions, verification expectations, and available Codex agents/skills.

Keep command examples aligned between `AGENTS.md` and `README.md`. Prefer concise notes over long explanations.

After docs edits, run `git diff --check`. Run Python compile checks only when Python files changed.
