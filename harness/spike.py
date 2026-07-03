#!/usr/bin/env python3
"""Phase 0 spike: prove transcript capture + skill-activation detection.

Runs headless Claude Code (`claude -p`) in throwaway workspaces:
  1x baseline        - no skill installed, trivial prompt (negative control)
  3x should-trigger  - dummy csv-helper skill installed, CSV prompt
  3x no-trigger      - same skill installed, unrelated prompt

Captures the full stream-json event stream per run, extracts token/cost/
duration/model/version, and tests detect_skill_activation() against all runs.

Throwaway quality: correctness over polish. Stdlib only. No canary text is
ever injected into the skill - we never modify the thing we measure.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "spike_fixtures"
TRANSCRIPT_DIR = REPO_ROOT / "transcripts"

SKILL_NAME = "csv-helper"

PROMPT_BASELINE = "Reply with the single word: ready"
PROMPT_TRIGGER = "load data.csv and tell me the column names"
PROMPT_NO_TRIGGER = "What is 2+2? Answer with just the number."


def clean_env() -> dict:
    """Strip CLAUDE* vars so a nested `claude` doesn't inherit this session's
    state (CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, CLAUDE_EFFORT skew, broken
    nested OAuth). Everything else (PATH, HOME, ANTHROPIC_API_KEY) passes
    through."""
    return {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}


def make_workspace(with_skill: bool) -> Path:
    ws = Path(tempfile.mkdtemp(prefix="skillbench-spike-"))
    if with_skill:
        skill_dir = ws / ".claude" / "skills" / SKILL_NAME
        skill_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / SKILL_NAME / "SKILL.md", skill_dir / "SKILL.md")
        shutil.copy(FIXTURES / "data.csv", ws / "data.csv")
    return ws


def claude_cli_version() -> str:
    out = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True, timeout=30,
        stdin=subprocess.DEVNULL, env=clean_env(),
    )
    return out.stdout.strip()


def run_claude(workspace: Path, prompt: str, tag: str, budget: float, timeout: int) -> dict:
    """One headless invocation. Returns a record with raw events + extracted metrics.

    Tries stream-json first; falls back to --output-format json only to salvage
    metrics — a fallback run is marked degraded and never scored for detection
    (json mode emits only the result event, so activation signals can't appear).
    """
    base_cmd = [
        "claude", "-p", prompt,
        "--model", "sonnet",
        "--max-budget-usd", str(budget),
        "--permission-mode", "bypassPermissions",
        "--setting-sources", "project",
    ]
    record = {"tag": tag, "prompt": prompt, "workspace": str(workspace)}

    cmd = base_cmd + ["--output-format", "stream-json", "--verbose"]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, env=clean_env(),
        )
    except subprocess.TimeoutExpired:
        record["infra_failure"] = f"timeout after {timeout}s"
        return record
    record["wall_time_s"] = round(time.monotonic() - start, 2)
    record["exit_code"] = proc.returncode
    record["output_format"] = "stream-json"

    events = parse_events(proc.stdout)
    if not events:
        # Salvage attempt only. NOTE: the failed stream-json attempt above may
        # have already billed an invocation whose cost we cannot see.
        record["degraded"] = "stream-json produced no events; fell back to json"
        cmd = base_cmd + ["--output-format", "json"]
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, env=clean_env(),
            )
        except subprocess.TimeoutExpired:
            record["infra_failure"] = f"timeout after {timeout}s (json fallback)"
            return record
        record["wall_time_s"] = round(time.monotonic() - start, 2)
        record["exit_code"] = proc.returncode
        record["output_format"] = "json"
        events = parse_events(proc.stdout)

    if not events:
        record["infra_failure"] = (
            f"no parseable events; exit={proc.returncode}; "
            f"stderr={proc.stderr[-2000:]!r}"
        )
        return record

    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"{tag}.jsonl"
    with open(transcript_path, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    record["transcript_path"] = str(transcript_path)
    record["events"] = events
    record.update(extract_metrics(events))

    # A run that "succeeded" per exit code can still be an API-level failure:
    # CC 2.1.178 emits result events with subtype "success" but is_error true
    # (e.g. auth failure), and budget cut-offs end runs early. All infra.
    if record.get("is_error"):
        record["infra_failure"] = f"result is_error=true: {record.get('result_text', '')[:200]}"
    elif not record.get("has_result"):
        record["infra_failure"] = "no result event in stream"
    elif record["exit_code"] != 0:
        record["infra_failure"] = f"nonzero exit code {record['exit_code']}"
    return record


def parse_events(stdout: str) -> list:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def extract_metrics(events: list) -> dict:
    """Pull model/version/tokens/cost/duration out of the event stream."""
    m = {"has_result": False}
    for ev in events:
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            m["model_string"] = ev.get("model")
            m["claude_code_version"] = ev.get("version") or ev.get("claude_code_version")
            m["session_id"] = ev.get("session_id")
            m["api_key_source"] = ev.get("apiKeySource")
            m["init_tools"] = ev.get("tools")
            m["init_slash_commands"] = ev.get("slash_commands")
            # Confirmed on 2.1.178: init has a `skills` list — the "loaded"
            # signal (skill available ≠ skill used) and the host-leak check.
            m["init_skills"] = ev.get("skills")
            m["init_plugins"] = ev.get("plugins")
            # Any field that plausibly lists loaded skills, for the
            # loaded-vs-activated distinction and host-leak check.
            m["init_skill_fields"] = {
                k: v for k, v in ev.items()
                if "skill" in k.lower() or "command" in k.lower() or "agent" in k.lower()
            }
        elif ev.get("type") == "result":
            usage = ev.get("usage") or {}
            m["has_result"] = True
            m["is_error"] = ev.get("is_error")
            m["tokens_in"] = usage.get("input_tokens")
            m["tokens_out"] = usage.get("output_tokens")
            m["cache_creation_tokens"] = usage.get("cache_creation_input_tokens")
            m["cache_read_tokens"] = usage.get("cache_read_input_tokens")
            m["cost_usd"] = ev.get("total_cost_usd")
            m["duration_ms"] = ev.get("duration_ms")
            m["num_turns"] = ev.get("num_turns")
            m["result_subtype"] = ev.get("subtype")
            m["result_text"] = (ev.get("result") or "")[:300]
    return m


def iter_tool_uses(events: list):
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield block


def detect_skill_activation(events: list) -> tuple:
    """Return (activated: bool, signal: str|None).

    Signals, strongest first:
      1. skill_tool_use  - explicit Skill/skill-named tool_use block invoking csv-helper
      2. skill_md_read   - a file-reading tool_use whose input path hits the SKILL.md
      3. content_echo    - skill path appears in non-system events
                           (fallback; system init excluded because a merely
                           *loaded* skill is listed there without being used)
    """
    # Signal 1: explicit skill invocation tool call.
    for block in iter_tool_uses(events):
        name = (block.get("name") or "").lower()
        input_str = json.dumps(block.get("input") or {}).lower()
        if "skill" in name and SKILL_NAME in input_str:
            return True, "skill_tool_use"

    # Signal 2: SKILL.md read via any file tool.
    for block in iter_tool_uses(events):
        input_str = json.dumps(block.get("input") or {})
        if f"skills/{SKILL_NAME}/SKILL.md" in input_str:
            return True, "skill_md_read"

    # Signal 3: skill path referenced in message content outside system events.
    for ev in events:
        if ev.get("type") == "system":
            continue
        blob = json.dumps(ev)
        if f"skills/{SKILL_NAME}/SKILL.md" in blob:
            return True, "content_echo"

    return False, None


def classify(rec: dict) -> str:
    """Bucket a finished record for the summary.

    infra              - run failed (timeout, is_error, no result, bad exit)
    degraded           - json fallback: metrics only, detection not evaluable
    true_negative      - expected no activation, none detected
    false_positive     - expected no activation, but detector fired (detector bug
                         or contamination - the serious failure mode)
    activated_detected - trigger run, activation seen (signal recorded)
    no_activation_evidence - trigger run, nothing in transcript references the
                         skill. Detector returns False only when zero evidence
                         exists, so this is either the skill honestly not
                         triggering (data, not a bug) or a signal type we don't
                         know about yet. Needs manual transcript inspection.
    """
    if "infra_failure" in rec:
        return "infra"
    if rec.get("output_format") == "json":
        return "degraded"
    activated, signal = detect_skill_activation(rec["events"])
    rec["detected_activation"] = activated
    rec["detection_signal"] = signal
    rec["tool_uses_seen"] = [
        {"name": b.get("name"), "input": b.get("input")}
        for b in iter_tool_uses(rec["events"])
    ]
    if rec["expected_activation"]:  # trigger runs
        return "activated_detected" if activated else "no_activation_evidence"
    # baseline + no-trigger runs: negative controls
    return "false_positive" if activated else "true_negative"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=float, default=0.15, help="max USD per invocation")
    ap.add_argument("--timeout", type=int, default=180, help="seconds per invocation")
    args = ap.parse_args()

    cli_version = claude_cli_version()
    print(f"claude CLI: {cli_version}")

    ws_plain = make_workspace(with_skill=False)
    ws_skill = make_workspace(with_skill=True)
    print(f"workspace (no skill):   {ws_plain}")
    print(f"workspace (with skill): {ws_skill}")

    plan = [("baseline", ws_plain, PROMPT_BASELINE, False)]
    plan += [(f"trigger-{i}", ws_skill, PROMPT_TRIGGER, True) for i in (1, 2, 3)]
    plan += [(f"notrigger-{i}", ws_skill, PROMPT_NO_TRIGGER, False) for i in (1, 2, 3)]

    records = []
    for tag, ws, prompt, expected in plan:
        print(f"\n=== {tag}: {prompt!r}")
        rec = run_claude(ws, prompt, tag, args.budget, args.timeout)
        rec["expected_activation"] = expected
        rec["category"] = classify(rec)
        if rec["category"] == "infra":
            print(f"  INFRA FAILURE: {rec['infra_failure']}")
        else:
            print(
                f"  format={rec['output_format']} turns={rec.get('num_turns')} "
                f"in={rec.get('tokens_in')} out={rec.get('tokens_out')} "
                f"cache_read={rec.get('cache_read_tokens')} "
                f"cost=${rec.get('cost_usd')} wall={rec.get('wall_time_s')}s"
            )
            print(
                f"  model={rec.get('model_string')} cc_version={rec.get('claude_code_version')} "
                f"auth={rec.get('api_key_source')}"
            )
            print(
                f"  category={rec['category']} "
                f"signal={rec.get('detection_signal')} expected={expected}"
            )
            print(f"  result: {rec.get('result_text', '')[:120]!r}")
        records.append(rec)

    print("\n" + "=" * 70)
    print("SUMMARY")
    buckets = {}
    total_cost = 0.0
    for rec in records:
        total_cost += rec.get("cost_usd") or 0.0
        buckets.setdefault(rec["category"], []).append(rec["tag"])
    for cat in ("activated_detected", "true_negative", "false_positive",
                "no_activation_evidence", "degraded", "infra"):
        if cat in buckets:
            print(f"  {cat}: {len(buckets[cat])} ({', '.join(buckets[cat])})")

    n_trigger_ok = len(buckets.get("activated_detected", []))
    n_neg_ok = len(buckets.get("true_negative", []))
    print(f"\ntrigger runs with activation detected: {n_trigger_ok}/3")
    print(f"negative controls clean:               {n_neg_ok}/4")
    if "false_positive" in buckets:
        print("  !! FALSE POSITIVES — detector bug or skill contamination, inspect transcripts")
    if "no_activation_evidence" in buckets:
        print("  ?? trigger run(s) with zero skill evidence in transcript — either the")
        print("     skill honestly did not trigger (data) or an unknown signal type.")
        print("     Inspect the transcript before trusting the detector.")
    print(f"total spike cost (visible): ${total_cost:.4f}")

    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    summary = [
        {k: v for k, v in rec.items() if k != "events"} for rec in records
    ]
    with open(TRANSCRIPT_DIR / "summary.json", "w") as f:
        json.dump({"cli_version": cli_version, "runs": summary}, f, indent=2)
    print(f"summary written to {TRANSCRIPT_DIR / 'summary.json'}")
    print(f"workspaces kept for inspection: {ws_plain} {ws_skill}")

    ok = n_trigger_ok == 3 and n_neg_ok == 4 and not any(
        c in buckets for c in ("false_positive", "infra", "degraded")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
