# Swingdesk Azure Deployment Plan

Status: Stable egress migration validated

## Scope

Operate the Swingdesk Flask application on Azure Container Apps with public HTTPS, persistent storage, dry-run trading, and a fixed outbound IP for Coinbase allowlisting. Preserve the existing Windows and Linux service options.

## Confirmed Context

- Subscription name: `wolffentpSub` (deployment scripts resolve and verify its ID at runtime)
- Proposed resource group: `rg-swingdesk-prod`
- Region: `eastus2`
- Access model: password-only application authentication over managed HTTPS
- Execution mode: user-approved dry-run deployment; live trading remains disabled

## Architecture

- Azure Container Registry stores the application image.
- Azure Container Apps runs one always-on replica with external HTTPS ingress and health probes.
- A Standard static public IP and NAT Gateway provide one fixed outbound address through a delegated Container Apps infrastructure subnet.
- The VNet-injected environment and app use versioned names so the current public app remains available until the replacement is verified.
- First-run deployment creates supporting infrastructure, builds the application in ACR, and only then creates the Container App.
- A dedicated user-assigned managed identity pulls images from ACR using `AcrPull`; registry admin credentials remain disabled.
- Azure Files mounts persistent application data at `/data` for settings, trade state, and the dashboard password hash.
- Container App secrets hold the dashboard password, session secret, and Coinbase credentials; secrets are supplied through an owner-only temporary parameters file that is always removed.
- GitHub Actions uses workload identity federation (OIDC), never a stored Azure client secret.

## Deployment State

- Replacement app: `swingdesk-zlhnrjhf-v2`
- Public URL: `https://swingdesk-zlhnrjhf-v2.politehill-0823ec58.eastus2.azurecontainerapps.io`
- Fixed egress IP: `20.161.129.15`
- Migration state: replacement verified; original app and environment retained for rollback
- External dependency: add `20.161.129.15` to the Coinbase API key IP allowlist before authenticated Coinbase calls can succeed

## Artifacts

- `infra/main.bicep`
- `scripts/Deploy-Azure.ps1` for context validation and idempotent infrastructure/image deployment
- `.github/workflows/deploy-azure.yml` for protected, manually dispatched federated deployment; a `main` trigger can be enabled after authorization
- README guidance for prerequisites, secret handling, one-time OIDC setup, validation, deployment, verification, rollback, cleanup, and cost boundaries

## Security Boundaries

- No secrets, tenant IDs, subscription IDs, or client IDs are committed.
- Deployment scripts must validate the active tenant/subscription before mutations and redact secrets.
- `DASHBOARD_HTTPS_ONLY=true` in Azure.
- Coinbase API permissions remain limited to required view/trade operations.
- Public access is protected by application login throttling and password authentication; it is not equivalent to private network isolation or Entra authentication.

## Validation

- Python test suite
- PowerShell parser validation
- Bicep restore/build and lint diagnostics
- Workflow YAML structural validation where tooling is available
- Docker build and Bash syntax checks where Docker/Bash are available
- Live public-health, runtime egress, storage-mount, and dry-run configuration checks

### Deployment Validation Checklist

- [x] All validation checks pass
	- [x] Core validation (authentication, Bicep build, deployment validation, and what-if)
	- [x] Container build path (local Docker unavailable; ACR build is the required deployment-time check)
	- [x] Azure Policy validation for `wolffentpSub`

## Section 7: Validation Proof

Validation run started: `2026-08-31T22:51:24-07:00`

- `pytest -q`: passed, 15 tests.
- `az bicep build --file .\infra\main.bicep --stdout`: passed.
- PowerShell parser check for `scripts/Deploy-Azure.ps1`: passed.
- Stable egress what-if: passed with 7 creates, no deletes, the current app and environment retained, and `DRY_RUN=True` on the replacement app.
- Stable egress deployment: succeeded. The replacement app reached a ready revision and exposed public HTTPS.
- Runtime verification: `/healthz` returned `200`, `/data` was mounted, and runtime outbound traffic reported `20.161.129.15`.
- Safety verification: the deployed replacement reports `DRY_RUN=True`.
- Coinbase verification: authenticated access still returns `401 Unauthorized`, as expected until `20.161.129.15` is added to the API key allowlist.
- Azure CLI context: `wolffentpSub` is enabled, selected as the default, and permits resource-group creation.
- Provider registration and region availability: all required providers are registered and all planned resource types support `eastus2`.
- Azure Policy: 11 assignments reviewed; no policy blocked the what-if preview.
- What-if: passed with 9 creates and no deletes or deny diagnostics. The deferred `AcrPull` role assignment was reported as expected because its principal ID is created during deployment.
- Local Docker build: not run because Docker is not installed on this workstation.

## Role Assignment Verification

- Status: Verified.
- Identity: dedicated user-assigned image-pull identity.
- Role: `AcrPull`, scoped to the Azure Container Registry.
- Issues: none; no broad resource-group or subscription role is granted to the workload.

## Deployment Gate

The user authorized and completed a billable dry-run deployment to `wolffentpSub`, resource group `rg-swingdesk-prod`, region `eastus2`. Live trading remains disabled.

## Cost And Rollback

- The Standard NAT Gateway has an hourly charge plus processed-data charges; the Standard static public IP and existing Container Apps, registry, storage, and log usage are also billable.
- Keep the original app and environment during Coinbase allowlisting and authenticated verification. This temporarily duplicates Container Apps environment resources.
- Roll back clients by selecting the original app URL. The fixed-egress resources can be removed only after the replacement is no longer needed and persistent state has been protected.
- Do not delete the shared storage account during rollback; both app generations use its Azure Files state.
