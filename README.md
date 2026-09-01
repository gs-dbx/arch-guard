# arch-guard

arch-guard is a pull-request governance engine for Databricks data pipelines. It compares changed pipeline code with a versioned architecture contract, reports precise deterministic violations, and adds an advisory foundation-model review for architectural and operational issues that are difficult to encode as syntax rules.

## Architecture

arch-guard has two review tiers:

1. The deterministic tier parses supported files and runs registered Python rules. These findings are reproducible, can have `error`, `warning`, or `note` severity, and are the only findings that can block a PR when enforcement is enabled.
2. The LLM tier sends each changed Databricks asset's complete current content, a compact contract summary, and existing linter findings to a Databricks Foundation Model serving endpoint. It reviews SDP/DLT, Spark Python, SQL, and Databricks job/pipeline YAML for judgment-based engineering concerns, emits only `warning` or `note` findings, and fails open if unavailable.

The deployment uses two repositories. The central `gs-dbx/arch-guard` repository owns the checker, parsers, rules, prompt, schema, and reusable workflow. Each pipeline repository owns its pipeline code, `arch-contract.yaml`, optional `.arch-waivers.yaml`, and a small caller workflow. The pipeline repository's contract is the source of truth for its sanctioned catalogs, tier graph, and naming policy; changing it is a reviewed architecture change, not a central-engine deployment.

The deterministic engine consumes `sanctioned_catalogs`, `catalog_convention`, `datasets`, `tiering.*.may_read_from`, and `naming`. Dataset policy validates approved dataset schemas, `dataset_name` identity tags, and domain-specific catalog placement for SDP/DLT assets. `schemas`, `external_sources`, general `required_tags`, `tiering.*.may_write_to`, and `overrides` remain forward-looking configuration.

## End-to-end flow

1. A contributor opens or updates a PR in a pipeline repository.
2. The pipeline workflow calls `.github/workflows/arch-guard-callable.yml` in this repository.
3. The reusable workflow checks out both repositories with full Git history, selects Python, verifies or installs dependencies, and passes Databricks authentication settings to the checker.
4. `arch_guard.check` validates the pipeline repository's `arch-contract.yaml` against `arch-contract.schema.json`. Invalid contracts terminate with exit code 2 and `arch-guard: FATAL — contract validation failed: ...`.
5. The checker uses `git diff --name-only BASE..HEAD` to select changed `.py`, `.sql`, `.yml`, and `.yaml` files. If `arch-contract.yaml` changed, it instead evaluates every tracked supported file.
6. Python, SQL, and Databricks Asset Bundle files are parsed into `FileContext` objects and dispatched to registered rules by file type.
7. If `FM_ENDPOINT` is set, the entire unified diff is reviewed by the FM endpoint. Any API, response-format, or schema error is logged and produces no FM findings.
8. `.arch-waivers.yaml` is loaded. A non-expired entry suppresses a finding only when `rule_id` and `file` match, plus `line` when the waiver specifies one.
9. Active findings are written to the Markdown GitHub job summary. Optional SARIF output and code-scanning annotations are available when the caller sets `sarif: true`.
10. Advisory mode always exits 0. Enforcing mode exits 1 only when an active deterministic error remains; warnings and notes do not block.

## What is checked

| Input | Recognition and parsing | Deterministic rule IDs |
|---|---|---|
| DLT/Lakeflow Python | A `.py` file containing `@dlt.table` or `@dlt.view`; AST extracts decorator metadata and literal `dlt.read()`/`dlt.read_stream()` sources | `catalog.unsanctioned`, `naming.table`, `naming.bronze_prefix`, `medallion.illegal_read` |
| Spark Python | Any other `.py` file; AST extracts `spark.table`, `spark.read.table`, `saveAsTable`, `writeTo`, and best-effort three-part names inside literal `spark.sql` strings | `catalog.unsanctioned`, `naming.table` for writes |
| SQL | `.sql`; line-oriented regex extracts three-part `catalog.schema.table` identifiers and classifies common write targets | `catalog.unsanctioned` |
| DAB YAML | A root file named exactly `databricks.yml` or `databricks.yaml`; YAML under `resources.pipelines` and `resources.jobs` is inspected | `catalog.unsanctioned`, `naming.pipelines`, `naming.jobs` |

Rule behavior is intentionally conservative. Dynamic Python names and non-three-part references cannot be catalog-checked. DLT tier inference comes from a literal `schema=` value, a `table_properties["schema"]` value, or a `bronze_`, `silver_`, or `gold_` logical-name prefix. Cross-file DLT source resolution is otherwise prefix-based because each rule receives one file at a time. DAB catalog inspection covers pipeline `catalog` and job task `named_parameters` whose key contains `catalog`; it does not search every possible Spark configuration shape.

### Rule catalog

- `catalog.unsanctioned` is an error. It reports a literal catalog not listed in `sanctioned_catalogs` in DLT decorators, Spark reads/writes, SQL references, DAB pipelines, or catalog-like DAB task parameters.
- `naming.table` validates DLT logical table/view names and non-DLT Spark write target names against `naming.tables.pattern`. Its severity comes from the contract.
- `naming.bronze_prefix` validates inferred bronze DLT names against `naming.bronze_table_prefix.pattern`. Its severity comes from the contract.
- `naming.pipelines` validates the DAB pipeline display `name`, or resource key when no name is set, against `naming.pipelines.pattern`.
- `naming.jobs` validates the DAB job display `name`, or resource key, against `naming.jobs.pattern`.
- `medallion.illegal_read` is an error. It reports an inferred DLT source tier that is not in the output tier's `may_read_from` list.
- `governance.dataset` checks that SDP/DLT schema names are approved datasets, `dataset_name` matches the schema, and domain-layer catalogs encode the dataset's owning domain.
- `parse.syntax_error` is an error returned when a DLT Python file cannot be parsed. Non-DLT Python syntax errors currently yield no Spark operations.
- `dab.parse_error` is an error returned when `databricks.yml` or `databricks.yaml` is invalid YAML.

FM rule IDs have the validated form `de.<category>.<specific>`, where category is `quality`, `lineage`, `pattern`, `ops`, `reliability`, `performance`, `testing`, or `governance`. Examples include `de.quality.no_expect`, `de.lineage.spark_read`, and `de.reliability.non_idempotent_write`.

## Finding sources and severity

The job summary's **Source** column is derived from the message. Messages beginning with `[LLM]` display as `LLM`; all others display as `Linter`.

Linter findings are deterministic. Contract-configured naming severities may be `error`, `warning`, or `note`; catalog and medallion violations are currently hard-coded errors. In advisory mode those errors are annotations only. With `advisory: false`, an active error makes the checker exit 1.

LLM findings must validate against the schema in `fm_review.py`, may only be warnings or notes, and must begin with `[LLM]` according to the prompt. The code also caps unexpected severities to warning. FM failure never crashes or blocks the check.

## Repository structure

Generated `__pycache__` files and local output artifacts are not source and should not be committed.

```text
arch-guard/
├── .github/workflows/
│   ├── arch-guard-callable.yml  # reusable workflow called by pipeline repos
│   └── arch-guard.yml           # this repository's own advisory PR check
├── arch_guard/
│   ├── __init__.py              # Python package marker
│   ├── check.py                 # CLI orchestration, diff selection, dispatch, output and exit status
│   ├── contract.py              # YAML loading, JSON Schema validation and tier/catalog helpers
│   ├── findings.py              # Finding value object, SARIF writer and job-summary writer
│   ├── fm_review.py             # Databricks SDK FM call, response validation and severity cap
│   ├── waivers.py               # waiver loading, matching and expiration handling
│   ├── parsers/
│   │   ├── __init__.py          # parser package marker
│   │   ├── dlt_python.py        # DLT AST parser: TableDef and SourceRef
│   │   ├── spark_python.py      # Spark AST parser: SparkOperation
│   │   └── sql_files.py         # best-effort SQL three-part-name parser
│   ├── prompts/
│   │   └── review_system.txt    # LLM role, scope, overlap controls and JSON contract
│   └── rules/
│       ├── __init__.py          # imports rule modules so decorators register them
│       ├── _base.py             # Rule, FileContext, @register and rules_for()
│       ├── catalog.py           # catalog rules for DLT and raw Python literals
│       ├── naming.py            # DLT table and bronze-prefix rules
│       ├── medallion.py         # DLT tier-read rule
│       ├── dab_config.py        # DAB catalog, pipeline-name and job-name rules
│       └── spark_jobs.py        # Spark/SQL catalog and Spark write-name rules
├── docs/
│   ├── ai-rule-context.md       # compact rule API context for AI-assisted development
│   ├── infrastructure.md        # environment and deployment guide
│   ├── user-guide.md            # general pipeline-contributor guide
│   └── writing-rules.md         # rule-authoring tutorial
├── tests/
│   ├── __init__.py              # test package marker
│   ├── helpers.py               # test contracts, temporary parsing and contexts
│   ├── fixtures/
│   │   ├── bronze_valid.py      # compliant bronze fixture
│   │   ├── databricks_bad_catalog.yml # invalid DAB catalog fixture
│   │   └── gold_illegal_read.py # bronze-to-gold violation fixture
│   ├── test_catalog.py          # current catalog rule tests
│   ├── test_medallion.py        # current tier-flow rule tests
│   ├── test_naming.py           # current naming rule tests
│   └── test_rules.py            # legacy pre-registry tests; not part of the passing discovery suite
├── arch-contract.yaml           # example/self-governance contract
├── arch-contract.schema.json    # contract JSON Schema
├── requirements.txt             # jsonschema, PyYAML and Databricks SDK
└── README.md                    # this document
```

## Adding a deterministic rule

The registry interface makes this a four-step change.

### 1. Create a rule module

Create `arch_guard/rules/required_tags.py`. A rule subclasses `Rule`, declares a dotted lowercase `rule_id`, declares one or more valid `applies_to` values, and returns `list[Finding]` from `check(ctx)`:

```python
from arch_guard.findings import Finding
from arch_guard.rules._base import FileContext, Rule, register


@register
class RequiredTagsRule(Rule):
    rule_id = "governance.missing_tag"
    applies_to = ["dlt_python"]

    def check(self, ctx):
        # type: (FileContext) -> list
        required = ctx.contract.get("required_tags", {}).get("tables", [])
        findings = []
        for table in ctx.tables:
            for tag in required:
                if tag not in table.table_properties:
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        message="Table '{}' is missing required tag '{}'.".format(
                            table.logical_name, tag),
                        file=ctx.file,
                        line=table.line,
                        severity="warning",
                    ))
        return findings
```

Valid contexts are:

- `dlt_python`: `ctx.tables` contains `TableDef` instances.
- `raw_python`: `ctx.spark_ops` contains `SparkOperation` instances.
- `sql`: `ctx.spark_ops` contains operations extracted from SQL.
- `dab_yaml`: `ctx.raw_config` contains parsed YAML.

Rules should consume the parsed context, return `[]` when their configuration is absent, emit one finding per violation, use the most accurate parsed line, and use contract-controlled severity when the relevant contract field exposes one. `check.py` requires no edit.

### 2. Register the module

Import it from `arch_guard/rules/__init__.py`:

```python
from arch_guard.rules import (  # noqa: F401
    catalog,
    naming,
    medallion,
    dab_config,
    spark_jobs,
    required_tags,
)
```

Importing triggers `@register`, which instantiates the class in the process-wide registry.

### 3. Add tests

Create `tests/test_required_tags.py`. Cover a compliant input, the specific violation, missing contract configuration, contract-driven severity when applicable, multiple assets, and accurate file/line output. Instantiate the rule with a `FileContext`; do not test through private registry state.

### 4. Run the test suite

```bash
cd /home/greg.skinner/gs-dbx/arch-guard
PYTHONPATH=. python3 -m unittest \
  tests.test_catalog tests.test_naming tests.test_medallion -v
PYTHONPATH=. python3 -m unittest tests.test_required_tags -v
```

The legacy `tests/test_rules.py` imports function names that predate the class-based registry and currently fails collection. Do not use bare `unittest discover` as a clean-suite signal until that file is migrated or removed.

## Tuning the LLM reviewer

Edit `arch_guard/prompts/review_system.txt` and review the change like rule code. The template includes customer-neutral playbook lenses for both declarative pipelines and ordinary jobs. It explicitly leaves naming conventions and catalog/schema topology to the architecture contract; use `docs/customer-architecture-decisions.md` to resolve those choices before encoding them.

`fm_review._build_system_prompt()` replaces two placeholders before the request:

- `{contract_summary}` becomes the sanctioned catalog names and each configured tier's `may_read_from` graph. It is deliberately compact; naming regexes, required tags, and external-source details are not currently included.
- `{linter_findings}` becomes one line per deterministic finding, including severity, rule ID, file, line, and message. When there are none it becomes `No linter findings for this diff.` The prompt tells the model not to duplicate those findings.

The full unified diff is a separate user message. Keep the output instructions aligned with `_FM_OUTPUT_SCHEMA`: `findings` is required; every item requires `rule_id`, `severity`, `file`, `line`, and `message`; the ID must match `dlt.[a-z_]+.[a-z_]+`; and additional finding properties are rejected except optional `rationale`. Test prompt changes against the configured endpoint and with malformed/fenced responses before release.

## Infrastructure requirements

The production pattern uses a self-hosted runner because the Databricks workspace IP access list admits a controlled runner egress address. PyPI availability is a separate concern: the workflow prefers the runner's pre-installed `/opt/databricks/isaac-omni/bin/python3` environment, avoiding public package downloads, but IP ACL reachability is the reason the self-hosted runner is required.

The runner needs Git, Bash, curl, Python, and either these importable packages or package-index access:

```text
jsonschema>=4.21
pyyaml>=6.0
databricks-sdk>=0.20
```

The workspace must allow the runner's static egress IP and the service principal must be able to use the workspace and query the named FM serving endpoint. The reusable workflow currently supports SDK client credentials and GitHub OIDC. See [docs/infrastructure.md](docs/infrastructure.md) for setup and troubleshooting.

## Wiring a pipeline repository

For the minimal caller, create `.github/workflows/arch-guard.yml`:

```yaml
name: arch-guard
on: {pull_request: {}}
jobs:
  arch-guard:
    uses: gs-dbx/arch-guard/.github/workflows/arch-guard-callable.yml@main
    with:
      contract: arch-contract.yaml
      runner: self-hosted
```

The reusable workflow defaults to advisory mode, so this is the complete eight-line caller. Production repositories should pin a release and pass the environment and Databricks inputs:

```yaml
      environment: demo
      databricks_host: ${{ vars.DATABRICKS_HOST }}
      databricks_client_id: ${{ vars.DATABRICKS_CLIENT_ID }}
      databricks_auth_type: client-credentials
      fm_endpoint: ${{ vars.FM_SERVING_ENDPOINT }}
    secrets:
      DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
```

Pin `uses:` and `arch_guard_ref` to a release tag or immutable commit in production. If the caller cannot read this repository with `github.token`, pass the optional `ARCH_GUARD_TOKEN` secret.

## Development

Create an isolated environment and install the three runtime dependencies:

```bash
cd /home/greg.skinner/gs-dbx/arch-guard
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the maintained deterministic tests:

```bash
PYTHONPATH=. python -m unittest \
  tests.test_catalog tests.test_naming tests.test_medallion -v
```

Run the CLI against a sibling pipeline repository from that repository so paths in the Git diff resolve correctly:

```bash
cd /home/greg.skinner/gs-dbx/vanilla-pipeline
BASE=$(git hash-object -t tree /dev/null)
HEAD=$(git rev-parse HEAD)
PYTHONPATH=../arch-guard python3 -m arch_guard.check \
  --contract arch-contract.yaml \
  --diff-base "$BASE" \
  --diff-head "$HEAD" \
  --sarif-out /tmp/arch-guard-findings.sarif \
  --summary-out /tmp/arch-guard-summary.md \
  --advisory
```

Unset `FM_ENDPOINT` for deterministic-only development. For an FM integration run, export the documented Databricks variables and set `FM_ENDPOINT` to an endpoint the principal can query.

## Roadmap

- **v1 — done:** contract validation, deterministic DLT rules, SARIF/job-summary output, advisory execution, and versioned architecture contracts.
- **v1.5 — Unity Catalog grounding:** resolve assets and metadata against Unity Catalog to reduce literal-only and same-file limitations.
- **v2 — done:** Databricks FM reviewer, structured response validation, Linter/LLM source labeling, overlap prevention, Spark Python/SQL/DAB coverage, and auditable waivers.
- **v2.5 — Contract Studio:** guided authoring and validation for architecture contracts, with reviewable generated changes.
- **v3 — enforcement:** required checks, blocking deterministic errors, and an authorized, audited override workflow.
