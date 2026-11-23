# ether-code

> 繁體中文：[README.zh-TW.md](README.zh-TW.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Understand first, change second.** Behavior doctrine for coding agents: audit the current state, define acceptance, pick the lightest sufficient depth of understanding, find the wheel before building, stop-loss when stuck, and show real output when done.

The wheel-lookup step (three prior-art lanes, wheel card, 7-level verdict) lives in the `wheel` skill of [royalskynet/wheel-it](https://github.com/royalskynet/wheel-it); this repo keeps only the how-to-write-code discipline and does not restate it.

**Skill type:** doc-only discipline, no runtime dependency. Optional dependency: [fixindex](https://github.com/royalskynet/fixindex) (symptom→fix lookup).

## Install

```bash
npx skills add https://github.com/royalskynet/ether-code
```

Installs to `~/.hermes/skills/ether-code/`. **Start a new session** for it to be indexed.

## Contents

The repo root is the skill `ether-code`: the body `SKILL.md` plus six `references/` read on demand:

| File | Read when |
|---|---|
| `references/orientation-routing.md` | choosing how deep to understand, using an existing graph, full-repo audit |
| `references/stop-loss.md` | stuck, or the finding list keeps growing |
| `references/acceptance.md` | before claiming done |
| `references/fixindex-usage.md` | looking up past fixes, or recording one |
| `references/agent-tools.md` | maintaining the agent system itself |
| `references/command-construction.md` | command-construction cases |

## Highlights

- **Auto mode routing** — targeted / graph-first / structure mapping / verify / audit / project memory; pick the lightest sufficient mode, escalate only when evidence is short.
- **Three layers** — audit current state and past fixes → find the wheel (run `/wheel`) → after three distinct approaches fail, record and stop.
- **Two stop-loss axes** — retry axis (keep trying this question?) and scope axis (fix this now?) are separate; don't mix them.
- **Acceptance discipline** — judge/guard tests need a sample that turns red; tool output is a claim; paste raw output.
- **Memory boundaries** — napkin (project traps), fixindex (root-caused, fixed defects), graphs (an index, not a fact) each keep their own lane.

## Host division

By default, stop and record what you learned after three distinct approaches fail. Follow a stricter retry limit if the host defines one. The counterfactual gate and the entry point for looking up past fixes belong in always-on global rules (CLAUDE.md / AGENTS.md / system prompt).

## When it triggers / doesn't

**Triggers:** complex multi-file development, unfamiliar libraries or services, unclear architecture or blast radius, external integrations, repeated failures.

**Does not trigger:** small local fixes, pure configuration, pure Q&A; a full-repo tech-debt audit only when asked.

## Origin

Extracted from [royalskynet/coding-hermes](https://github.com/royalskynet/coding-hermes) (a fork of NousResearch/hermes-agent), lived next to `wheel` in wheel-it, and became this repo on 2026-10-18. See [HISTORY.md](HISTORY.md).

## License

MIT. Copyright (c) 2026 royalskynet.
