# skill-bench

Open-source A/B benchmarking harness for Claude Code skills. This file is the project's permanent context — read it fully before doing anything.

## What skill-bench is

A harness that measures whether Claude Code skills actually work. Method: run identical tasks through headless Claude Code twice — once with a skill installed, once without (control) — across a matrix of tasks × conditions × n_runs. Capture transcripts, token counts, cost, wall time. Grade outputs with deterministic graders. The delta between conditions is the skill's measured value. Output: a public leaderboard + pre-registered methodology.

Nobody has published rigorous numbers on this — the skills ecosystem runs on vibes and install counts. skill-bench is the first pre-registered, receipts-included benchmark of that ecosystem.

## Locked decisions (do not revisit, do not "improve")

- v1 scope: Python data-science tasks only. Claude Code only. One skill per condition. Single pinned model (Sonnet).
- Primary metric: deterministic grader pass rate. NO LLM-as-judge anywhere in v1.
- Explicitly out of scope for v1: multi-skill combos, other agents (Codex/Gemini), SQL tasks, any web backend (leaderboard is a static site), CI action.
- Stack: Python 3.11+, minimal dependencies (stdlib + pandas/numpy where needed, click or argparse for CLI, no frameworks). Docker for sandboxing (Phase 1+). Results as JSONL. MIT license.
- Every run record contains: run_id, task_id, condition, skill_commit_sha, model_string, claude_code_version, tokens_in, tokens_out, cost_usd, wall_time_s, grader_output, transcript_path.
- Retries ONLY on infra failures (API errors, container death). Agent doing badly = data, never retried.
- Skills are pinned to commit SHAs in a manifest. Results are stamped with model + Claude Code version + date.
- Never inject canary text (or any modification) into a skill being measured. We never modify the thing we measure.

## Roadmap (build order is sacred — each phase ends with a git commit and STOPS for review)

- **Phase 0 (done first): spike** — prove transcript capture + skill-activation detection. Artifacts: `harness/spike.py`, dummy skill + fixture, `SPIKE_FINDINGS.md`.
- **Phase 1:** Docker sandbox image (pinned Claude Code + Python env, network locked to Anthropic API) + matrix runner CLI + JSONL writer + timeouts/turn caps.
- **Phase 2:** Tasks 3 & 4 (dirty-numeric-parsing, fan-out-join) — fixtures, prompts, graders, grader unit tests (known-good / known-bad / edge reference solutions must pass before any API spend). Pilot n=3.
- **Phase 3:** Tasks 1, 2, 5 (leakage trap, time-series CV trap, notebook repair), same standard.
- **Phase 4:** `skills/manifest.yaml` (8–10 most-installed DS skills + 2–3 famous general skills, pinned SHAs) + `claims.yaml` per task mapping which skill claims justify testing it.
- **Phase 5:** full pilot run, n=5 per cell, overnight batches.
- **Phase 6:** analysis (Wilson intervals per task, stratified bootstrap for aggregate deltas, effect sizes + CIs, never bare point estimates) + static leaderboard site from results JSON.
- **Phase 7:** `PROTOCOL.md` finalized (pre-registration), README findings-forward, launch assets.

## Communication principles (shapes every phase; framing, not scope creep)

Rigorous work travels when the finding is clear and the evidence is one click away. These principles govern how results get communicated. (All example numbers below are hypothetical illustrations — no such results exist.)

1. **Findings-forward, not tool-forward.** Once results exist, the README leads with them (e.g., hypothetically: "skill X moved pass rate 23% → 71%"); the harness is the footnote. People share findings, not repos.
2. **Receipts, not vibes.** Every leaderboard number links to raw transcripts + exact commit SHAs + model version. One click from claim to evidence. Critics who audit and find it holds become distributors.
3. **Pre-registration = armor.** PROTOCOL.md locks tasks/graders/metrics before the full run. "We committed to the methodology before seeing results" kills the cherry-picking attack and is itself shareable.
4. **The negative result is the story.** If most skills show no effect, that IS the finding — "you installed 12 skills; n of them measurably matter." Never bury nulls; nulls with confidence intervals are the product.
5. **One number per skill.** Leaderboard headline = pass-rate delta with Wilson CI. Tokens/cost/time deltas one click deeper. Complexity kills sharing.
6. **Cost transparency.** Publish exactly what the full benchmark cost to run. Replication feels possible → reproducibility becomes distribution.
7. **Shareable units.** Leaderboard renders per-skill cards (OG-image-friendly: skill name, delta, CI, verdict) so a single result travels on X/HN without the whole site.
8. **Name every effect.** "Dead skill" (no measurable delta), "tax" (worse than control), "carry" (big positive delta). Defined in PROTOCOL.md at lock time; surfaced publicly only once results exist.
9. **Claim only what exists.** Future work in future tense; smoke tests never dressed as validation studies; every public number backed by a committed artifact. The receipts practice starts at Phase 0 (`receipts/`), not at launch.

## Engineering norms

- Correctness over polish in spikes; grader unit tests before any API spend in task phases.
- Don't over-engineer, don't add abstractions for future phases, don't create config systems until a phase demands them.
- If `claude -p` flags differ from what a spec or doc says, check `claude --help` and adapt — record the adaptation below.
- If a load-bearing assumption fails after honest attempts, STOP and report — never build around an unproven assumption.

## Adaptations log

- **2026-07-03, Claude Code 2.1.178:** no `--max-turns` flag exists in this CLI version. Spend/runaway guard adapted to `--max-budget-usd <amount>` (works with `--print`). Re-check when pinning the Phase 1 image version.
