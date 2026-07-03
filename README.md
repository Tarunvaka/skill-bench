# skill-bench

**Do Claude Code skills actually work? No one has published a controlled A/B experiment. This harness will.**

There are thousands of Claude Code skills — installable instruction packs that promise to make the agent better at specific work. People install them based on GitHub stars and vibes. What's missing is a controlled experiment showing that installing a skill changes what the agent actually produces — for better, worse, or not at all.

skill-bench runs that experiment: the same task, through headless Claude Code, **with and without the skill**, n runs per condition (pilot n=5; final n sized from pilot variance and fixed in the pre-registered protocol), graded by deterministic checkers. The delta is the skill's measured effect. All of it will be public and pre-registered before the full run, with receipts.

```
   same task · same model · same prompt
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌───────────────┐       ┌───────────────┐
│    control    │       │   treatment   │
│   no skill    │       │   skill on    │
└───────┬───────┘       └───────┬───────┘
        ▼                       ▼
  deterministic grader → pass/fail per run
                    │
                    ▼
      Δ pass rate = headline effect
```

## Design commitments (locked before any result exists)

These are rules of the game, committed now — the artifacts they describe land in the phases below.

- **No LLM-as-judge. Anywhere.** Every task will ship with a deterministic grader — a program that checks outputs against a known answer key. Graders get unit-tested against known-good, known-bad, and edge-case reference solutions *before any benchmark run*.
- **Pre-registered.** Tasks, graders, metrics, and the tested-skill list get locked and published in a timestamped release tag **before** the full run.
- **Receipts.** Every number links to raw run transcripts, the skill's exact commit SHA, the model string, and the Claude Code version. This starts now: the Phase 0 spike's own transcripts are committed in [receipts/](receipts/).
- **Nulls get published.** If a famous skill moves nothing, that's not a failed experiment — that's the finding.
- **We never touch the skills.** Skills are tested exactly as shipped, pinned to a commit SHA. No canary edits, no instrumentation injected into the thing being measured.
- **Bad agent runs are data.** Retries happen only on infrastructure failures (API errors, container death). An agent doing badly is a result, never rerolled.
- **Uncertainty always shown.** Wilson intervals per task, stratified bootstrap CIs on aggregate deltas — and per-cell intervals are estimation, not hypothesis tests: no significance hunting across 50+ cells.

## What Phase 0 established

The two riskiest assumptions survived contact with reality ([full findings](SPIKE_FINDINGS.md), [raw transcripts](receipts/)):

**1. Skill activation is machine-detectable.** When Claude Code actually *uses* a skill, the event stream contains an explicit marker:

```json
{"type": "tool_use", "name": "Skill", "input": {"skill": "csv-helper", "args": "data.csv"}}
```

7/7 spike runs classified correctly — 3/3 skill-relevant prompts fired it, 4/4 controls stayed clean. (7 runs, one dummy skill, deliberately easy negatives — a smoke test that the detection mechanism exists, not a validation study; Phase 1 hardens it with adversarial negatives.) Usefully, *loaded* (installed, listed in the session init event) and *activated* (actually invoked) are separately measurable — so the leaderboard can report a skill's **activation rate** independently of its effect. A skill that never fires can't be helping.

**2. Full telemetry is capturable.** Tokens in/out, cache usage, dollar cost, wall time, turns, resolved model string, Claude Code version — all extracted programmatically per run from `claude -p --output-format stream-json`.

Phase 0 also caught two landmines that now shape the design: the Claude Code CLI **auto-updated itself mid-day** (2.1.178 → 2.1.200), and the `sonnet` model alias **switched underlying models the same day** (claude-sonnet-4-6 → claude-sonnet-5). A benchmark that doesn't pin both is measuring a moving target — Phase 1's sandbox will pin both.

## What gets measured

Five Python data-science tasks, each built around a known agent failure mode — dirty numeric parsing, fan-out/join, a target-leakage trap, a time-series CV trap, notebook repair. Tasks get calibrated in the pilot so control pass rates land mid-range; a task at ceiling or floor is flagged and can't generate verdicts. Per skill × task cell:

| metric | meaning |
|---|---|
| Δ pass rate | did the skill change *correctness*? (headline metric) |
| activation rate | did the skill even fire when it should? |
| Δ tokens / Δ cost | what does the skill cost you per request? |
| Δ wall time | does it make runs slower? |

Δ pass rate is intent-to-treat: computed over all treatment runs whether or not the skill fired. Activation rate is reported alongside so dilution is visible.

Tested skills: 8–10 widely-used data-science skills plus 2–3 well-known general-purpose ones. The selection metric (a public popularity measure, stated with its as-of date), the full list, and pinned commit SHAs are published in the manifest before the protocol locks — selection is the most gameable step in a benchmark like this, so it locks first.

## Status

- [x] **Phase 0 — activation-detection spike.** Verdict: GO. ([findings](SPIKE_FINDINGS.md) · [receipts](receipts/))
- [ ] Phase 1 — Docker sandbox (pinned CC + model), matrix runner, JSONL results
- [ ] Phase 2–3 — five tasks: fixtures, prompts, graders + grader unit tests
- [ ] Phase 4 — skill manifest (pinned SHAs) + per-task claim mapping
- [ ] Phase 5 — pilot run (n=5 per cell) to size the final n
- [ ] Phase 6 — analysis + static leaderboard
- [ ] Phase 7 — pre-registered protocol published, then the full run and results

**No results yet — by design.** The methodology gets locked and published before the full run. Watch this repo if you want the results the day they publish — and star it so you can find it again when they do.

## Run the spike yourself

```bash
git clone https://github.com/Tarunvaka/skill-bench && cd skill-bench
python3 harness/spike.py   # needs Claude Code CLI installed + authenticated; ~$0.50 of API use
```

Note: the spike runs headless Claude Code with `--permission-mode bypassPermissions` inside throwaway temp workspaces — read [harness/spike.py](harness/spike.py) (it's short) before running.

The activation-detection result (the `Skill` tool_use signature, telemetry capture) regenerates from that one command. The version-drift and auth findings in [SPIKE_FINDINGS.md](SPIKE_FINDINGS.md) were point-in-time observations — your version numbers and costs will differ, which is itself the point.

## Who's running this

[Tarun Vaka](https://github.com/Tarunvaka), independently. I author none of the skills that will be tested, and take nothing from skill authors. The tested-skill list is fixed at protocol lock; complaints about task fairness are welcome as issues *before* the lock — that's what the pre-registration window is for.

## FAQ

**Why only Claude Code / Python DS / one model?** v1 is deliberately narrow: one agent, one domain, one pinned model, one skill per condition. A narrow benchmark done rigorously beats a broad one done loosely. Breadth comes after the method survives public scrutiny.

**Why no LLM judge? Everyone uses them.** LLM judges have preferences, drift, and failure modes that are themselves unmeasured. A benchmark about "does X actually work" can't rest on a grader whose own accuracy is vibes. Deterministic checkers are less flexible — that's the price of being unarguable.

**Will you test my skill?** Post-v1, if the method holds up: yes, that's the point of building this in the open.

## License

MIT
