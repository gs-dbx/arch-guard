# arch-guard infrastructure and deployment

This guide deploys arch-guard for pipeline repositories whose deterministic checks run locally in GitHub Actions and whose advisory review calls a Databricks Foundation Model endpoint.

## 1. Runner requirements

Use a self-hosted runner with a stable outbound IP. The hard requirement is workspace reachability: a Databricks workspace protected by IP access lists rejects a changing GitHub-hosted runner address before authentication. Public PyPI availability is not the reason for self-hosting; the current workflow separately avoids PyPI by preferring a Databricks-managed Python environment with dependencies already installed.

Register the runner with the label used by callers, currently `self-hosted`. It needs:

- outbound HTTPS to GitHub and the Databricks workspace;
- a static or predictably NATed egress IPv4 address;
- Git, Bash, curl, and standard Unix tools;
- `/opt/databricks/isaac-omni/bin/python3`, or a system `python3` and `pip3`;
- importable `yaml`, `jsonschema`, and `databricks.sdk`, or access to an approved package index;
- sufficient workspace for two Git checkouts and SARIF output.

Confirm the execution identity and egress address on the runner:

```bash
id
git --version
curl -fsS https://ifconfig.me
/opt/databricks/isaac-omni/bin/python3 --version
/opt/databricks/isaac-omni/bin/python3 -c 'import yaml, jsonschema, databricks.sdk; print("dependencies ready")'
```

The reusable workflow prints the observed egress address in **Show runner egress IP**. Treat that output as diagnostic; production ACL automation should use the network team's known NAT address.

## 2. Databricks workspace and service principal

Create a Databricks service principal for arch-guard rather than using a human PAT. Record its application/client ID. For the currently deployed client-credentials path, create an OAuth secret and store it only as a GitHub Actions secret.

The principal needs workspace access and permission to query the selected serving endpoint. In the workspace admin UI:

1. Open **Settings → Identity and access → Service principals**.
2. Add or select the arch-guard service principal.
3. Grant the **Workspace access** entitlement. Do not grant unrestricted cluster creation or admin unless another workload genuinely requires it.
4. Open **Serving → Endpoints**, choose the FM endpoint, open **Permissions**, and grant **Can Query** to the principal.

For endpoints governed through SQL-style securables, a workspace administrator can grant query permission with the Databricks CLI:

```bash
databricks serving-endpoints update-permissions "$FM_ENDPOINT" \
  --json "{\"access_control_list\":[{\"service_principal_name\":\"$DATABRICKS_CLIENT_ID\",\"permission_level\":\"CAN_QUERY\"}]}"
```

The command uses the endpoint and application ID already exported for connectivity testing. Because an update-permissions request changes access, first inspect existing permissions and preserve required entries:

```bash
databricks serving-endpoints get-permissions "$FM_ENDPOINT"
```

## 3. Verify FM endpoint access

From the runner, set client credentials without setting `DATABRICKS_AUTH_TYPE`; the SDK auto-detects OAuth M2M from the client ID and secret:

```bash
# Set these four values from the workspace and service-principal records.
read -r -p 'Databricks host: ' DATABRICKS_HOST
read -r -p 'Service-principal application ID: ' DATABRICKS_CLIENT_ID
read -r -s -p 'Service-principal OAuth secret: ' DATABRICKS_CLIENT_SECRET; echo
read -r -p 'FM endpoint name: ' FM_ENDPOINT
export DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET FM_ENDPOINT

/opt/databricks/isaac-omni/bin/python3 - <<'PY'
import os
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

w = WorkspaceClient()
response = w.serving_endpoints.query(
    name=os.environ["FM_ENDPOINT"],
    messages=[ChatMessage(role=ChatMessageRole.USER, content="Reply with OK")],
    max_tokens=16,
)
print(response.choices[0].message.content)
PY
```

Run this only in a trusted interactive runner session; do not paste a secret into logs or commit it. A successful response verifies DNS/TLS, IP ACL admission, credential exchange, workspace entitlement, endpoint existence, and `CAN_QUERY`.

## 4. GitHub configuration

Host `.github/workflows/arch-guard-callable.yml` in the central `gs-dbx/arch-guard` repository. Under **Settings → Actions → General → Access**, allow repositories owned by the organization to access reusable workflows. In an enterprise-managed organization, select the organization/user access level that exposes the repository to the intended user-owned repositories; do not make the source public solely to enable reuse.

The customer pipeline repository stores:

| Type | Name | Required when |
|---|---|---|
| Variable | `DATABRICKS_HOST` | FM review enabled |
| Variable | `DATABRICKS_CLIENT_ID` | client credentials or OIDC |
| Variable | `FM_SERVING_ENDPOINT` | FM review enabled |
| Secret | `DATABRICKS_CLIENT_SECRET` | `databricks_auth_type: client-credentials` |
| Secret | `ARCH_GUARD_TOKEN` | only when `github.token` cannot read the central repo |

Use **Settings → Secrets and variables → Actions**. Host, client ID, and endpoint are configuration, not credentials, and belong in variables. The OAuth client secret belongs in secrets. If the caller passes `environment: demo`, also create the `demo` GitHub environment and apply its protection rules; variables may be repository- or environment-scoped as long as the workflow can resolve them.

The workflow requires these permissions:

```yaml
permissions:
  contents: read
  pull-requests: write
  security-events: write
  checks: write
  id-token: write
```

`id-token: write` is required for OIDC and harmless but unused by the interim M2M path. SARIF is disabled by default because code-scanning availability and token policy vary by organization. Set the reusable workflow input `sarif: true` only where code scanning is available; upload remains `continue-on-error`, and the job summary remains authoritative.

## 5. Authentication

### Current: OAuth client credentials

The sample pipeline passes:

```yaml
with:
  databricks_host: ${{ vars.DATABRICKS_HOST }}
  databricks_client_id: ${{ vars.DATABRICKS_CLIENT_ID }}
  databricks_auth_type: client-credentials
  fm_endpoint: ${{ vars.FM_SERVING_ENDPOINT }}
secrets:
  DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
```

For this mode the reusable workflow intentionally exports an empty `DATABRICKS_AUTH_TYPE`. This lets the SDK select `oauth-m2m`; explicitly forcing a mismatched auth type caused credential discovery failures during setup.

### Production target: GitHub OIDC workload identity federation

OIDC removes the stored Databricks client secret. It needs account-administrator setup before changing the caller:

1. Create or select the Databricks service principal at account level and assign it to the workspace.
2. Create a service-principal federation policy whose issuer is `https://token.actions.githubusercontent.com`.
3. Set the audience expected by Databricks and restrict the subject to the repository and GitHub environment, for example `repo:gs-dbx/vanilla-pipeline:environment:demo`.
4. Ensure the workspace identity has Workspace access and endpoint `CAN_QUERY`.
5. Create the matching GitHub environment and retain `id-token: write`.
6. Change the caller to `databricks_auth_type: github-oidc` and stop passing `DATABRICKS_CLIENT_SECRET`.

```yaml
with:
  environment: demo
  databricks_host: ${{ vars.DATABRICKS_HOST }}
  databricks_client_id: ${{ vars.DATABRICKS_CLIENT_ID }}
  databricks_auth_type: github-oidc
  fm_endpoint: ${{ vars.FM_SERVING_ENDPOINT }}
```

The subject must match exactly. Branch-, pull-request-, and environment-based GitHub subjects are different; the reusable workflow's `environment` field deliberately makes the claim stable and tightly scoped.

## 6. Python environment

The first choice is:

```text
/opt/databricks/isaac-omni/bin/python3
/opt/databricks/isaac-omni/bin/pip3
```

The workflow tests the Python executable, exports `PYTHON` and `PIP` through `GITHUB_ENV`, and then runs:

```bash
$PYTHON -c "import yaml, jsonschema, databricks.sdk"
```

When that succeeds, it bypasses PyPI entirely. This avoids public-index DNS/SSL restrictions observed on the self-hosted runner and uses its pre-installed Python 3.12 dependencies. When the environment is absent or imports fail, the workflow falls back to system `python3`/`pip3` and `pip install -r .arch-guard/requirements.txt`; therefore configure an internal index or preinstall packages if public PyPI is unavailable.

## 7. IP ACL management

Find the workspace's active IP access lists before changing them:

```bash
databricks ip-access-lists list
read -r -p 'IP access-list ID: ' IP_ACCESS_LIST_ID
export IP_ACCESS_LIST_ID
databricks ip-access-lists get "$IP_ACCESS_LIST_ID"
```

Add the runner's static egress address as a `/32` while preserving every existing allowed address. With an authenticated workspace administrator token, the REST update shape is:

```bash
curl --fail-with-body --request PATCH \
  --header "Authorization: Bearer $DATABRICKS_TOKEN" \
  --header 'Content-Type: application/json' \
  "$DATABRICKS_HOST/api/2.0/ip-access-lists/$IP_ACCESS_LIST_ID" \
  --data "{\"label\":\"github-self-hosted-runners\",\"list_type\":\"ALLOW\",\"ip_addresses\":[\"$RUNNER_EGRESS_CIDR\"],\"enabled\":true}"
```

Set `RUNNER_EGRESS_CIDR` to the verified static address with `/32` before the PATCH. The payload replaces the list's address collection; fetch it first and include existing entries. Make the change from an already allowed administrative network to avoid locking out the operator. A dynamic runner address will eventually change and recreate the 403, so use a static NAT gateway/egress IP rather than repeatedly expanding the ACL.

## 8. Onboarding a pipeline repository

Use this checklist:

1. Create the pipeline repository and add a schema-valid `arch-contract.yaml` at its root.
2. Add `.arch-waivers.yaml` containing `waivers: []` if exceptions will be supported.
3. Under GitHub Actions variables, set `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `FM_SERVING_ENDPOINT`.
4. For interim M2M, set the `DATABRICKS_CLIENT_SECRET` Actions secret. For OIDC, create the federation policy and matching GitHub environment instead.
5. Confirm the central workflow repository is accessible. Add `ARCH_GUARD_TOKEN` only if the built-in token cannot check it out.
6. Confirm a runner matching `self-hosted` is online and its egress `/32` is in the workspace allow list.
7. Add `.github/workflows/arch-guard.yml`:

```yaml
name: arch-guard
on:
  pull_request:
    paths: ["pipelines/**", "jobs/**", "notebooks/**", "**/*.sql", "databricks.yml", "arch-contract.yaml"]
permissions:
  contents: read
  pull-requests: write
  security-events: write
  checks: write
  id-token: write
jobs:
  arch-guard:
    uses: gs-dbx/arch-guard/.github/workflows/arch-guard-callable.yml@main
    with:
      contract: arch-contract.yaml
      advisory: true
      runner: self-hosted
      environment: demo
      databricks_host: ${{ vars.DATABRICKS_HOST }}
      databricks_client_id: ${{ vars.DATABRICKS_CLIENT_ID }}
      databricks_auth_type: client-credentials
      fm_endpoint: ${{ vars.FM_SERVING_ENDPOINT }}
    secrets:
      DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
```

8. Create a PR that changes a selected path. Verify checkout, Python selection, deterministic output, FM call, job summary, and SARIF upload independently.

Pin both the reusable workflow reference and its `arch_guard_ref` input to a tested release before enabling enforcement.

## 9. Troubleshooting

### Workspace returns 403 because of the IP ACL

Typical symptom: the SDK or a direct workspace request receives `403 Forbidden` before a useful endpoint permission response. The workflow's egress step prints an address followed by `if FM review is blocked, add <ip>/32 to the workspace IP ACL.`

Fix: compare that address with the enabled allow list, add the runner NAT `/32`, and retest from the runner. If the address changes between runs, provision static egress.

### SDK says credentials cannot be configured or found

Symptoms include errors equivalent to `cannot configure default credentials` or `default auth: cannot configure default credentials`.

Fix for M2M: verify all three of `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET` reach the run step, and do not force `DATABRICKS_AUTH_TYPE=client-credentials`; the current workflow leaves it empty so SDK auto-detection selects OAuth M2M. Fix for OIDC: verify `id-token: write`, the GitHub environment, issuer/audience/subject federation policy, and `DATABRICKS_AUTH_TYPE=github-oidc`.

### Endpoint rejects `temperature`

Claude-backed endpoints used during setup rejected the `temperature` query parameter. The fix was to remove it and send only `name`, `messages`, and `max_tokens`. Do not reintroduce `temperature=0` without verifying that every configured endpoint accepts it.

### Response content is a list, not a string

Claude-compatible SDK responses may represent `message.content` as a list of text blocks. Calling `.strip()` on that value leads to an error such as `'list' object has no attribute 'strip'`. Current `fm_review.py` joins each block's `text` before JSON parsing. If a new provider returns a different block structure, update `_extract_json_from_response` and add a test rather than weakening schema validation.

### FM output is not valid JSON or fails schema validation

The checker logs either:

```text
arch-guard [fm]: response is not valid JSON — ...
arch-guard [fm]: response failed schema validation — ...
```

The FM tier then returns no findings by design. Inspect `review_system.txt`, endpoint truncation, `max_tokens`, code fences, required fields, the `de.<category>.<specific>` ID pattern, and allowed severities. Do not pass unvalidated model text into SARIF.

### FM API failure does not fail the job

The expected log is:

```text
arch-guard [fm]: API call failed — ...
```

This is fail-open behavior, not proof that review succeeded. Resolve network, auth, endpoint name, and `CAN_QUERY`; deterministic findings remain valid meanwhile.

### Package install cannot reach PyPI or fails TLS setup

Earlier system/setup-python paths failed behind restricted DNS or corporate CAs. Confirm `/opt/databricks/isaac-omni/bin/python3` exists and imports all three packages. Preinstall from the approved internal source rather than depending on public PyPI during a PR run.

### Runner expression or label does not schedule

The current reusable input is a string used directly by `runs-on`. Pass `runner: self-hosted` or another visible label. Do not pass an encoded group/labels object to this workflow version and do not wrap the input in `fromJSON`.

### Contract validation fails before checking code

The checker writes:

```text
arch-guard: FATAL — contract validation failed: ...
```

It exits 2 even in advisory mode. Validate required fields, allowed `env`/severity values, naming regex strings, and `additionalProperties: false` constraints against `arch-contract.schema.json`.

### Optional SARIF upload fails but the summary exists

Private-repository code-scanning availability or token permissions can reject `github/codeql-action/upload-sarif`. SARIF defaults off; when explicitly enabled, the upload uses `continue-on-error: true`. Verify `security-events: write` and GitHub code-scanning availability, while continuing to use the job summary as the authoritative output.
