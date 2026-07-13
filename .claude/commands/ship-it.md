---
description: "Ship the current branch as a PR with auto-merge enabled (redact-api project ship-it)"
argument-hint: "[--base <branch>] [--draft]"
allowed-tools: ["Bash", "Read"]
---

# Ship It (redact-api)

Project-level ship-it for `Lexington-Concord/redact-api`. Runs after
`/prep-pr` finishes its self-review and quality gates. Creates a PR, enables
auto-merge, and runs the finalize verification.

**Arguments:** "$ARGUMENTS"

**Review policy (operator-set, 2026-07-13):** CI is the merge gate — the
template's `ci.yml` (ruff, mypy, pytest) must be green; auto-merge lands the
PR when it is. No human pre-merge review step. Functionality is reviewed
post-merge on the dev cluster.

**Safety caveat:** changes touching the redaction verify gate
(`redact_api/redaction/verify_gate.py` once it exists) must never weaken gate
semantics to make CI pass. If a failing test is "fixed" by loosening a match
threshold or skipping a check, BLOCK instead of shipping.

---

## Step 1: Parse arguments

Base defaults to `main`; override with `--base <branch>`. Pass `--draft`
through if provided.

## Step 2: Confirm branch is pushed

```bash
BRANCH=$(git branch --show-current)
git push -u origin "$BRANCH" 2>&1
```

If push fails (e.g., diverged), BLOCK — do not force-push.

## Step 3: Create the PR

```bash
TITLE=$(git log --format='%s' -1)
RANGE_BODY=$(git log --format='- %s' "origin/${BASE:-main}..HEAD")
```

```bash
gh pr create \
  --base "${BASE:-main}" \
  --head "$BRANCH" \
  ${DRAFT:+--draft} \
  --title "$TITLE" \
  --body "$(cat <<EOF
## Summary

$RANGE_BODY

## Merge gate

CI (ruff + mypy + pytest) is the review gate for this repo (operator policy);
functionality is reviewed post-merge on the dev cluster.

🤖 Shipped via /prep-pr + project /ship-it
EOF
)"
```

If the invoking context (ticket, `/prep-pr`) supplies a richer body, prefer it
over this default. Reference the ticket (`Closes #N`) when the branch maps to
one.

## Step 4: Enable auto-merge

```bash
PR_NUMBER=$(gh pr view --json number -q .number)
gh pr merge "$PR_NUMBER" --auto --squash
```

Squash is this org's merge convention. Skip only for `--draft` PRs.

## Step 5: Run finalize verification

The contract that proves /ship-it completed its side effects. /prep-pr re-runs
this and requires `status: "ok"` with a non-null `pr_number`.

```bash
~/.claude/scripts/prep_pr_finalize.py verify --require-automerge --json
```

Print the JSON output verbatim — do not summarize. (For `--draft` ships, drop
`--require-automerge`.)

---

## Failure modes

- **Push fails (diverged):** BLOCK. Rebase/merge main first.
- **PR creation fails:** BLOCK with the `gh` error verbatim.
- **Auto-merge enable fails:** BLOCK — don't leave it silently unset.
- **Finalize verification fails:** BLOCK with the JSON; do not paper over.

No fallbacks. No silent retries. Errors surface via /prep-pr's BLOCK handling.
