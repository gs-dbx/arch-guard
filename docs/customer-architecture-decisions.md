# Customer architecture decisions

The data-engineering playbook supplies review lenses, not customer policy. Record these decisions before turning them into deterministic rules or authoritative LLM context. Until decided, the reviewer must not prescribe them.

## Naming

### Agreed

- Environments are `dev`, `test`, `preprod`, and `prod`.
- The catalog prefix is `csb`.
- Bronze and silver storage is domain-specific.
- Bronze uses a domain-specific catalog named `csb_{env}_{domain}_stage`.
- Silver uses a domain-specific catalog named `csb_{env}_{domain}_cleansed`.
- Gold outputs leave the domain catalog and are published to either `csb_{env}_analytics` or `csb_{env}_apps`, according to their consumer and serving purpose.
- Every approved dataset may publish to either gold destination: `analytics`, `apps`, or both.
- Schemas represent datasets. A dataset normally keeps the same schema name as it moves from its domain `stage` catalog to `cleansed` and then into `analytics` or `apps`.
- Every dataset schema requires the `dataset_name` tag. For now, this is the only mandatory dataset-level tag, and its value must match the dataset/schema name.

### Still to decide

- What is the authoritative set of domain tokens, and who approves a new domain?
- What guidance determines whether a particular produced asset belongs in `analytics` versus `apps`?
- Can two domains use the same dataset/schema name, and if so, how are collisions handled in the shared `analytics` and `apps` catalogs?
- What is the initial whitelist of datasets and each dataset's owning domain?
- Which assets beyond catalogs need conventions: tables/views, volumes, jobs, pipelines, tasks, service principals, and compute policies?
- Which meaning belongs in names versus tags?
- How are abbreviations, acronyms, pluralization, separators, and maximum lengths handled?
- Which conventions block delivery versus warn, and what is the migration/exception path?

## Catalog and schema topology

### Agreed

- Catalogs encode environment, domain, and medallion role: bronze and silver use separate domain-specific `stage` and `cleansed` catalogs.
- Gold is consumer-oriented: analytical products publish to the environment's shared `analytics` catalog; application-serving products publish to its shared `apps` catalog.
- Schemas provide dataset identity and normally preserve that identity across the medallion flow.
- Dataset identity is also declared with a required schema tag: `dataset_name=<schema name>`.

### Still to decide

- Are environments also isolated by workspace, account, workspace bindings, storage credentials, or deployment identity?
- Where do shared reference data, sandboxes, quarantine, operational metadata, and test fixtures live?
- How are cross-domain reads, cross-region data, external locations, shares, and ownership delegated?
- Which topology choices are requirements, and which are overridable defaults?

## Workload and operating model

- What is the default choice among SDP, notebook/Python/SQL job tasks, dbt, and external orchestration?
- What latency classes, recovery objectives, backfill volumes, and cost constraints matter?
- Which ingestion sources and CDC semantics are in scope, including deletes and out-of-order handling?
- What retry, timeout, concurrency, notification, checkpoint, and idempotency policies are required?
- Which data-quality failures warn, quarantine, drop, or fail?
- What metadata, ownership, classification, lineage, testing, and promotion gates are mandatory?

Encode stable enforceable decisions in `arch-contract.yaml`; keep nuanced guidance in the system prompt. Naming and catalog topology should remain absent from playbook-derived prompt guidance except as explicit contract context.
