# Phase 0 Spike Findings

Environment tested: Claude Code CLI **2.1.178**, macOS (darwin 25.3.0), Python 3.13, model alias `sonnet` → `claude-sonnet-4-6`. Date: 2026-07-03.

## Verdict

PENDING — authenticated runs in progress. Everything below the activation section is already empirically confirmed (init/result events are emitted even by $0 auth-failed runs, which made free schema probing possible).

## Invocation recipe that works

```
claude -p "<prompt>" \
  --output-format stream-json --verbose \
  --model sonnet \
  --max-budget-usd 0.15 \
  --permission-mode bypassPermissions \
  --setting-sources project
```

- `--output-format stream-json` with `-p` requires `--verbose`; emits one JSON event per line on stdout. Confirmed parseable line-by-line.
- The `--output-format json` fallback emits ONLY the final result event (single compact line) — no init, no assistant events, so **activation detection is impossible in json mode**. The harness treats fallback runs as degraded (metrics only, never scored for detection).
- **No `--max-turns` flag exists in 2.1.178** (it exists in older docs/SDK). Adapted to `--max-budget-usd` as the runaway guard. Re-verify whichever version gets pinned in the Phase 1 image.

## Token / cost / metadata capture

Two events carry everything the run record needs:

- `{"type":"system","subtype":"init"}` — fields confirmed on 2.1.178: `model` (resolved string, e.g. `claude-sonnet-4-6`), `claude_code_version` (`"2.1.178"`), `session_id`, `apiKeySource`, `tools`, `slash_commands`, **`skills`** (list of loaded skill names), `plugins`, `agents`, `permissionMode`, `cwd`.
- `{"type":"result"}` — fields confirmed: `usage.input_tokens`, `usage.output_tokens`, `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens`, `total_cost_usd`, `duration_ms`, `num_turns`, `modelUsage` (per-model breakdown), `is_error`, `api_error_status`, `result` (final text), `permission_denials`.
- **Trap: `subtype` stays `"success"` even when `is_error` is `true`** (e.g. auth failure). Never trust `subtype`; check `is_error`. Raw excerpt from a real failed run:

```json
{"type":"result","subtype":"success","is_error":true,"api_error_status":401,
 "duration_ms":2192,"num_turns":1,
 "result":"Failed to authenticate. API Error: 401 Invalid authentication credentials",
 "total_cost_usd":0,"usage":{"input_tokens":0,"output_tokens":0,...}}
```

## Loaded vs activated — two different signals

- **Loaded**: the skill name appears in the init event's `skills` list. Confirmed: a workspace-local `.claude/skills/csv-helper/SKILL.md` shows up as `"skills": ["csv-helper", ...]` when invoked with `--setting-sources project` from that workspace.
- **Activated**: evidence the model actually used it mid-run (see next section). A loaded skill that is never used must count as NOT activated — init-event presence alone is insufficient and excluded from the detector.

## Activation signature

PENDING — filled in from authenticated trigger/no-trigger runs (raw event excerpt to be included).

Detector implemented in `harness/spike.py` (`detect_skill_activation`), signals strongest-first:
1. `skill_tool_use` — a `tool_use` block whose tool name contains "skill" and whose input references `csv-helper`.
2. `skill_md_read` — any file-tool `tool_use` whose input path contains `skills/csv-helper/SKILL.md`.
3. `content_echo` — the SKILL.md path appearing in any non-system event (system init excluded: loaded ≠ used).

No canary text was injected into the skill — we never modify the thing we measure.

## Isolation findings (matter for measurement validity)

- Without `--setting-sources project`, a headless run **inherits the host machine's user settings**: SessionStart hooks fired and plugin skills (2 host plugins, 21 host skills) loaded into the nested session. Any of that would contaminate an A/B measurement.
- With `--setting-sources project`, plugins list is empty and user skills are gone — only the workspace skill plus Claude Code **built-in** skills remain (`design-sync`, `verify`, `code-review`, etc.). Built-ins are identical across both arms of a condition, so they don't bias the delta, but they exist — document, don't ignore.
- Nested-environment leakage: a `claude` subprocess spawned from inside a Claude Code session inherits `CLAUDE*` env vars (including `CLAUDE_EFFORT`, which would skew token counts). The spike strips all `CLAUDE*` vars (`clean_env()` in spike.py). The Phase 1 Docker sandbox eliminates this class of problem entirely.

## Auth fragility (Phase 1 relevant)

- Subscription OAuth tokens in the macOS keychain expire (~short-lived) and the CLI cannot refresh them when the refresh token is absent — headless runs then fail 401 with `apiKeySource: "none"` while interactive/desktop sessions keep working via host-side refresh. Symptom is silent-ish: `subtype:"success"`, `is_error:true`, cost $0.
- Under subscription auth, expect `total_cost_usd` to be reported but verify against `modelUsage`; for Phase 1, an `ANTHROPIC_API_KEY` inside the Docker sandbox is the predictable choice (real billing, no keychain, no browser flow).
- The harness must treat `is_error:true`, missing result event, or nonzero exit as **infra failure** (excluded + retryable), never as agent data.

## Version-dependent / fragile list

1. `--max-turns` missing on 2.1.178 (use `--max-budget-usd`).
2. `stream-json` requires `--verbose` with `-p`.
3. `result.subtype` unreliable; use `is_error`.
4. Init event field is `claude_code_version` (not `version`).
5. json fallback mode carries no activation evidence.
6. Built-in skills present even with `--setting-sources project`.

## Spike cost

PENDING — reported from `transcripts/summary.json` after authenticated runs.
