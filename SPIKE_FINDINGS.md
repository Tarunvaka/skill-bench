# Phase 0 Spike Findings

Environment tested: Claude Code CLI **2.1.178 → 2.1.200** (auto-updated mid-spike day — see fragility #1), macOS (darwin 25.3.0), Python 3.13, model alias `sonnet` (resolved to `claude-sonnet-4-6` in the morning, **`claude-sonnet-5` by evening** — see fragility #2). Date: 2026-07-03. Total spike cost: **$0.46** (7 invocations).

## Verdict: GO

Both risky assumptions hold:

1. **Transcript + metrics capture works.** Full event stream, token counts, cost, duration, model string, and CC version all programmatically extractable from `claude -p --output-format stream-json`.
2. **Skill activation is machine-detectable, reliably.** 7/7 runs classified correctly: 3/3 should-trigger runs produced an explicit `Skill` tool_use event; 4/4 negative controls (1 baseline without skill + 3 unrelated-prompt runs with skill installed) produced zero activation evidence.

## Activation signature (the headline result)

When Claude Code uses a skill, the event stream contains an assistant message with a `tool_use` block naming the `Skill` tool and the skill being invoked. Raw excerpt from run `trigger-1` (transcripts/trigger-1.jsonl):

```json
{
  "type": "tool_use",
  "id": "toolu_01Hf2BSgypkGMv4QFsUmj2U4",
  "name": "Skill",
  "input": {
    "skill": "csv-helper",
    "args": "data.csv"
  },
  "caller": { "type": "direct" }
}
```

Detector (`detect_skill_activation` in harness/spike.py), signals strongest-first:
1. `skill_tool_use` — `tool_use` block whose tool name contains "skill" and whose input references the skill name. **Fired on 3/3 trigger runs. Primary signal.**
2. `skill_md_read` — any file-tool `tool_use` whose input path contains `skills/<name>/SKILL.md`. Fallback; never needed in the spike.
3. `content_echo` — SKILL.md path in any non-system event. Weak fallback; never needed.

No canary text was injected into the skill — we never modify the thing we measure.

## Loaded vs activated — two different signals

- **Loaded**: skill name appears in the init event's `skills` list (confirmed: workspace `.claude/skills/csv-helper/` shows up as `"skills": ["csv-helper", ...]`).
- **Activated**: the `Skill` tool_use fires mid-run. A loaded-but-unused skill stays in the init list and never produces signal 1 — confirmed by the 3 no-trigger runs (skill loaded, prompt "What is 2+2?", zero activation events, 1 turn, ~$0.02/run).

This distinction is measurable data in its own right: the harness can report a skill's *activation rate* separately from its *effect on outcomes*.

## Invocation recipe that works

```
claude -p "<prompt>" \
  --output-format stream-json --verbose \
  --model sonnet \
  --max-budget-usd 0.15 \
  --permission-mode bypassPermissions \
  --setting-sources project
```

- `stream-json` with `-p` requires `--verbose`; emits one JSON event per line on stdout.
- The `--output-format json` fallback emits ONLY the final result event — no activation evidence possible. The harness marks fallback runs degraded and never scores them for detection.
- **No `--max-turns` flag in 2.1.178/2.1.200.** Adapted to `--max-budget-usd` as the runaway guard.

## Token / cost / metadata capture

Two events carry everything the run record needs:

- `{"type":"system","subtype":"init"}` — `model` (resolved string), `claude_code_version`, `session_id`, `apiKeySource`, `tools`, `slash_commands`, `skills`, `plugins`, `agents`, `permissionMode`, `cwd`.
- `{"type":"result"}` — `usage.input_tokens`, `usage.output_tokens`, `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens`, `total_cost_usd`, `duration_ms`, `num_turns`, `modelUsage`, `is_error`, `api_error_status`, `result`, `permission_denials`.

Measured example (trigger-1): 6,243 in / 375 out, 117k cache-read, $0.135, 12.4s, 5 turns. Baseline: 3,239 in / 4 out, $0.05, 3.1s, 1 turn.

**Trap: `subtype` stays `"success"` even when `is_error` is `true`.** Raw excerpt from a real auth-failed run:

```json
{"type":"result","subtype":"success","is_error":true,"api_error_status":401,
 "result":"Failed to authenticate. API Error: 401 Invalid authentication credentials",
 "total_cost_usd":0,"usage":{"input_tokens":0,"output_tokens":0}}
```

## Isolation findings (measurement validity)

- Without `--setting-sources project`, headless runs inherit host user settings: SessionStart hooks fired and 2 host plugins / 21 host skills loaded into the nested session. Contamination confirmed live.
- With `--setting-sources project`: plugins empty, user skills gone. Claude Code **built-in** skills remain (`verify`, `code-review`, etc.) — identical across both arms, so no delta bias, but documented.
- Nested `claude` inherits `CLAUDE*` env vars (including `CLAUDE_EFFORT`, which skews token use). The spike strips them (`clean_env()`). Docker (Phase 1) eliminates the class.

## Version-dependent / fragile list

1. **The CLI auto-updates.** 2.1.178 at spike start, 2.1.200 by evening, same machine, same day. Phase 1 MUST pin the Claude Code version in the Docker image or results are stamped against a moving target.
2. **Model aliases drift.** `--model sonnet` resolved to `claude-sonnet-4-6` in morning probes and `claude-sonnet-5` in the evening runs. Phase 1 MUST pin the full model string (e.g. `claude-sonnet-5`), never the alias. The run record's `model_string` comes from the init event (resolved), not from the flag — already correct.
3. `stream-json` requires `--verbose` with `-p`.
4. `result.subtype` unreliable; use `is_error`.
5. Init field is `claude_code_version` (not `version`).
6. json fallback mode carries no activation evidence.
7. Subscription (OAuth) auth reports `apiKeySource: "none"` in init yet still populates `total_cost_usd` — the field works, but Phase 1 should use `ANTHROPIC_API_KEY` in the sandbox for predictable, keychain-free auth. Keychain OAuth tokens expire and headless runs then 401 (`is_error:true`, cost $0) while interactive sessions keep working via host-side refresh — treat as infra failure, retry after re-auth.

## Raw artifacts

- Per-run event streams: committed at [`receipts/spike-2026-07-03/`](receipts/spike-2026-07-03/) (one `.jsonl` per run + `summary.json`). Fresh runs write to `transcripts/` (gitignored); regenerate with `python3 harness/spike.py`.
- Detection reliability: 3/3 trigger detected (all via primary signal), 4/4 negative controls clean, 0 infra failures, 0 degraded runs.
