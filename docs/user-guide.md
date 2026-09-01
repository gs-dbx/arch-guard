# arch-guard User Guide

**For data engineers using a pipeline repo that has arch-guard enabled.**

This guide explains what arch-guard is, what happens when it flags your code,
how to fix findings, and what to do when you need an exception.

---

## Contents

1. [What is arch-guard?](#1-what-is-arch-guard)
2. [What does it check?](#2-what-does-it-check)
3. [The check runs automatically — what you will see](#3-the-check-runs-automatically)
4. [Reading a finding](#4-reading-a-finding)
5. [Fixing common findings](#5-fixing-common-findings)
6. [When you cannot fix it: requesting a waiver](#6-requesting-a-waiver)
7. [Emergency override for an entire PR](#7-emergency-override-for-an-entire-pr)
8. [Changing the rules (for platform engineers)](#8-changing-the-rules)
9. [Frequently asked questions](#9-frequently-asked-questions)

---

## 1. What is arch-guard?

arch-guard is an automated check that runs on every pull request in this repo.
It reads your pipeline code and compares it against the team's agreed architecture
rules — things like which data catalogs are approved for use, how data must flow
through the bronze → silver → gold layers, and how tables and jobs must be named.

You do not install or run arch-guard yourself. It runs automatically whenever you
open or update a PR that touches pipeline code.

**There are two modes:**

| Mode | Behaviour |
|---|---|
| Advisory | Findings are reported but the PR is not blocked. You can still merge. |
| Enforcing | Any error-severity finding blocks the PR. You must fix it or file a waiver before merging. |

Your repo is currently in **advisory mode** unless the platform team has told you otherwise.

---

## 2. What does it check?

arch-guard checks four things:

### Sanctioned catalogs
Your pipelines may only write to and read from a specific approved list of
Unity Catalog catalogs. Writing to a catalog not on the list — for example,
a personal dev catalog or a catalog from a legacy system — is flagged as an error.

**Applies to:** DLT pipelines, regular Spark jobs, SQL files, `databricks.yml`.

### Naming conventions
Table names, pipeline names, and job names must follow the agreed patterns.
For example, bronze tables must start with `raw_`, and table names must be
lowercase snake_case. Violations are flagged as errors or warnings depending
on the rule.

**Applies to:** DLT pipelines, regular Spark jobs, `databricks.yml`.

### Medallion data flow
Data must flow in the correct direction: external sources → bronze → silver → gold.
A gold pipeline reading directly from a bronze table (skipping the silver
transformation layer) is flagged as an error.

**Applies to:** DLT pipelines.

### Anti-patterns (when FM API is configured)
When an LLM endpoint is configured, arch-guard also reviews the diff for
best-practice violations that rules cannot catch — things like bronze tables
with no data quality expectations, or tables missing required metadata.
These findings are always advisory (warnings only, never errors).

**Applies to:** All Python pipeline files.

---

## 3. The check runs automatically

When you open a PR or push a new commit to an open PR, arch-guard runs within
about 60 seconds. You will see it in two places:

### The Checks tab
At the bottom of your PR page, under **"All checks have passed"** (or failed),
you will see an `arch-guard` entry. Click **Details** to go to the workflow run.

### The job summary
Inside the workflow run, click the **Summary** tab on the left. You will see a
table like this:

```
## arch-guard — 2 finding(s)

Posture: advisory (non-blocking)
Errors: 1   Warnings: 1

|   | Severity | Rule                   | File:Line               | Message                              |
|---|----------|------------------------|-------------------------|--------------------------------------|
| 🔴 | error   | catalog.unsanctioned   | pipelines/ingest.py:14  | Table targets catalog 'legacy_wh'... |
| 🟡 | warning | naming.bronze_prefix   | pipelines/ingest.py:14  | Bronze table should start with raw_  |
```

If there are waived findings they appear collapsed below the table.

---

## 4. Reading a finding

Each finding has four fields:

| Field | What it means |
|---|---|
| **Severity** | `error` must be fixed or waived before the PR can merge (in enforcing mode). `warning` is advisory. |
| **Rule** | The specific rule that fired. See [section 5](#5-fixing-common-findings) for what each rule means. |
| **File:Line** | Exactly where in your code the problem was found. |
| **Message** | A plain-English description of the problem including the specific value that failed. |

---

## 5. Fixing common findings

### `catalog.unsanctioned`
**What it means:** Your code references a catalog that is not in the approved list.

**How to fix:**
1. Check the message — it will tell you which catalog was found and list the approved ones.
2. Update your code to use one of the approved catalogs.
3. If you need to use a new catalog that doesn't exist yet, see [section 8](#8-changing-the-rules).

**Where this fires:** DLT decorator (`catalog="..."`), `spark.table(...)`,
`spark.read.table(...)`, `df.write.saveAsTable(...)`, SQL `FROM` / `INSERT INTO`,
`databricks.yml` pipeline or job config.

---

### `naming.table`
**What it means:** A table name doesn't match the required pattern (`^[a-z][a-z0-9_]+$` by default — lowercase snake_case only).

**How to fix:** Rename the table. Change `RawOrders` → `raw_orders`.
In DLT, update the `name=` kwarg on the `@dlt.table` decorator.

---

### `naming.bronze_prefix`
**What it means:** A bronze-tier table doesn't start with the required prefix (`raw_`).

**How to fix:** Rename the table to start with `raw_`. Example: `orders` → `raw_orders`.
This is a **warning**, so it won't block your PR, but the platform team will ask you to fix it.

---

### `naming.pipelines`
**What it means:** A pipeline name in `databricks.yml` doesn't match `^plp_(bronze|silver|gold)_[a-z0-9_]+$`.

**How to fix:** Rename the pipeline in `databricks.yml`. Example:
`orders_pipeline` → `plp_bronze_orders_ingest`.

---

### `naming.jobs`
**What it means:** A job name in `databricks.yml` doesn't match `^job_[a-z0-9_]+$`.

**How to fix:** Rename the job. Example: `Orders ETL` → `job_orders_etl`.

---

### `medallion.illegal_read`
**What it means:** A pipeline is reading from a tier it is not allowed to read from.
Most commonly: a gold pipeline reading directly from bronze, skipping the silver
data quality layer.

**How to fix:**
- Gold pipelines must read from silver tables only.
- Silver pipelines must read from bronze tables only.
- If you need data from a lower tier, it must pass through the intermediate tier first.

Example: instead of `gold_report` → `dlt.read("raw_orders")`, route it through
a silver table: `gold_report` → `dlt.read("clean_orders")` (where `clean_orders`
is a silver table that reads from `raw_orders`).

---

### `de.<category>.*` (LLM findings)
**What it means:** The LLM reviewer flagged a best-practice issue.
These are always **warnings** and are always advisory — they will never block your PR.

**How to fix:** Read the message and rationale. These are suggestions, not requirements.
If you disagree with the finding, you can ignore it or file a waiver to suppress it
permanently for that file.

---

## 6. Requesting a waiver

A waiver tells arch-guard: "I have reviewed this finding, I understand the risk,
and I am choosing to accept it." Waivers are tracked in git so there is a permanent
record of who approved what and why.

**When to use a waiver:**
- You have a legitimate reason not to fix the finding (legacy code, migration in progress, etc.)
- The finding is a false positive (the rule fired incorrectly on your code)
- The fix would require a large coordinated change tracked separately

**When NOT to use a waiver:**
- As a shortcut to avoid fixing something that should be fixed
- When you are not sure — ask the platform team first

### Step-by-step: submitting a waiver

**Step 1 — Find the finding details.**

In the job summary, note the exact:
- `rule_id` (e.g. `catalog.unsanctioned`)
- `file` (e.g. `pipelines/ingest.py`)
- `line` (optional but recommended)

**Step 2 — Edit `.arch-waivers.yaml` in your repo.**

Open `.arch-waivers.yaml` at the root of your pipeline repo. You will see:

```yaml
waivers: []
```

Add an entry:

```yaml
waivers:
  - rule_id: catalog.unsanctioned
    file: pipelines/legacy_ingest.py
    line: 22
    reason: >
      This table migrates data from our legacy warehouse (legacy_wh) which
      is being decommissioned in Q1 2027. The migration is tracked in
      DATA-4821. Until the migration is complete, this catalog reference
      is intentional.
    approved_by: data-platform-admins
    expires: 2027-03-01
```

**Fields explained:**

| Field | Required | Description |
|---|---|---|
| `rule_id` | Yes | Exact rule ID from the finding (e.g. `catalog.unsanctioned`) |
| `file` | Yes | Repo-relative path exactly as shown in the finding |
| `line` | No | Specific line number. Omit to waive all instances of this rule in the file |
| `reason` | Yes | Plain English justification. Be specific — vague reasons will be rejected in review |
| `approved_by` | Yes | GitHub team or username of the person approving this waiver |
| `expires` | No | ISO date (YYYY-MM-DD). After this date the waiver is ignored and the finding becomes active again. Use this for temporary suppressions |

**Step 3 — Commit the change and push.**

```bash
git add .arch-waivers.yaml
git commit -m "waiver: suppress catalog.unsanctioned on legacy_ingest.py (DATA-4821)"
git push
```

**Step 4 — The check re-runs automatically.**

When you push, arch-guard re-runs. If the waiver matches the finding, the finding
moves from the active table to the collapsed "waived findings" section in the summary.
It is still visible for audit purposes but no longer counts toward the pass/fail decision.

**Step 5 — Request review.**

Tag `@data-platform-admins` in the PR description explaining the waiver.
They will review the reason and approve or request changes.

### What a waived finding looks like in the summary

```
✅ 1 waived finding(s)

| Rule                 | File:Line              | Reason                     |
|----------------------|------------------------|----------------------------|
| catalog.unsanctioned | pipelines/ingest.py:22 | Legacy migration (DATA-4821) (expires 2027-03-01) |
```

---

## 7. Emergency override for an entire PR

If you need to bypass **all** arch-guard findings for a single PR — for example,
an urgent hotfix — you can apply the override label. This is a coarser tool than
a waiver: it bypasses everything, not just a specific finding.

**This label is restricted.** Only members of `data-platform-admins` can apply it.

**Label name:** `arch-override-approved`

To use it:
1. Request the label from a member of `data-platform-admins`
2. Explain the reason in the PR description
3. The label is applied to the PR and the check is bypassed for that PR only

The use of this label is logged permanently in the PR's label history on GitHub.

---

## 8. Changing the rules

All rules are configured in `arch-contract.yaml` at the root of your pipeline repo.
This file is the single source of truth for what is and is not allowed.
**Every change to this file is a reviewed PR — there are no silent rule changes.**

### Adding a new sanctioned catalog

```yaml
sanctioned_catalogs:
  - name: dev_analytics
    env: dev
  - name: new_team_catalog      # ← add this
    env: dev
```

Open a PR with this change. It takes effect on the next workflow run after merge.

### Changing a naming pattern

```yaml
naming:
  tables:
    pattern: "^[a-z][a-z0-9_]+$"   # ← edit this regex
    severity: error
```

### Promoting a warning to an error (tightening enforcement)

```yaml
naming:
  bronze_table_prefix:
    pattern: "^raw_"
    severity: error   # was: warning
```

After this change, any PR that adds a bronze table without the `raw_` prefix
will fail the check (in enforcing mode).

### Changing the medallion flow

```yaml
tiering:
  bronze:
    may_read_from: [external]
    may_write_to: [bronze]
```

Only the platform team should edit the `tiering` section. Incorrect changes here
can produce false positives across all pipeline repos.

### Requesting a completely new rule

New rule logic lives in `arch-guard/arch_guard/rules/`. Open a PR against the
`arch-guard` repo with your rule implementation. See `docs/writing-rules.md`
in that repo for the step-by-step guide.

---

## 9. Frequently asked questions

**Q: The check passed but I know my code has a problem — why wasn't it caught?**

arch-guard only checks code that is new or changed in the PR diff. Pre-existing
violations in files that you did not touch will not be flagged. If you want to
scan all files, the platform team can run a full scan manually.

---

**Q: I fixed the finding but the check still shows it.**

Push your fix and the check will re-run automatically. If the finding still appears,
the fix may not have addressed the exact line arch-guard flagged. Check the
`File:Line` in the finding against your current code.

---

**Q: The LLM flagged something but I disagree with it.**

LLM findings are always advisory (warnings only). You can ignore them without
consequence. If the same false positive keeps appearing, file a waiver with
`rule_id: dlt.anti_pattern.<whatever>` to suppress it permanently for that file.

---

**Q: Can I test arch-guard locally before pushing?**

Yes. If the `arch-guard` repo is cloned alongside your pipeline repo:

```bash
cd your-pipeline-repo

# Check everything against HEAD
BASE=$(git hash-object -t tree /dev/null)
HEAD=$(git rev-parse HEAD)

PYTHONPATH=../arch-guard python3 -m arch_guard.check \
  --contract arch-contract.yaml \
  --diff-base "$BASE" \
  --diff-head "$HEAD" \
  --sarif-out /tmp/findings.sarif \
  --advisory

# Or use the convenience script if your repo has one:
./run_check.sh
```

---

**Q: Who do I contact if I think a rule is wrong?**

Open a PR against `arch-contract.yaml` to change the configuration (section 8),
or reach out to `@data-platform-admins` on Slack / in the PR.

---

**Q: Why can't I just add `# arch-ignore` to suppress a finding inline?**

Inline suppression is not supported in v1. The deliberate choice is to keep
suppression in `.arch-waivers.yaml` so all exceptions are visible in one place
and require a code review. Inline suppression will be considered for a future
release.

---

**Q: I added a waiver but it's not suppressing the finding.**

Check that:
1. The `rule_id` in the waiver exactly matches the `rule_id` in the finding (case-sensitive)
2. The `file` path exactly matches (use the path as shown in the finding, not a relative shorthand)
3. The waiver hasn't expired (`expires` date has not passed)
4. You pushed the waiver file change to your branch
