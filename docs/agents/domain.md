# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`AGENTS.md`** at the repo root: the authoritative project constitution (§0 mandates also reading `docs/设计文件/核心原则.md` and `docs/设计文件/架构设计.md`). These define the five-layer L0–L4 domain vocabulary; they always win over generic conventions.
- **`CONTEXT.md`** at the repo root: a single-context glossary. It does **not exist yet** — it is created lazily by `/domain-modeling` (reached via `/grill-with-docs` and `/improve-codebase-architecture`) when terms actually get resolved.
- **`docs/决策记录/`**: this repo's ADR directory (not `docs/adr/`). Files are named `ADR-XXXX-<中文标题>.md` (e.g. `ADR-0034-OCellus离线扰动锚点契约.md`). Read the ADRs that touch the area you're about to work in.

If `CONTEXT.md` doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront.

## File structure

Single-context repo:

```
/
├── AGENTS.md                          ← authoritative constitution
├── CONTEXT.md                         ← (created lazily, may not exist)
├── docs/
│   ├── 决策记录/                       ← ADRs: ADR-XXXX-<标题>.md
│   ├── 设计文件/                       ← 核心原则.md, 架构设计.md
│   └── 计划文件/                       ← MVP计划.md
└── src/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the terms as defined in `AGENTS.md`, `docs/设计文件/核心原则.md`, and (once it exists) `CONTEXT.md` — e.g. the five-layer scale (L0–L4), `contract demonstrator`, `reference model`, `emergence candidate`. Don't drift to synonyms the project explicitly avoids, and don't reframe the project as a "multi-agent platform" or "LLM agent framework" (AGENTS.md §1).

If the concept you need isn't defined anywhere, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR in `docs/决策记录/`, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0014 (L3 自适应拓扑治理), but worth reopening because…_
