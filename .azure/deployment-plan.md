# Swingdesk Azure Deployment Plan

Status: Ready for Validation

## Scope

Prepare, but do not execute, a repeatable deployment of the existing Swingdesk Flask application to Azure Container Apps. Preserve the existing Windows and Linux service options.

## Confirmed Context

- Subscription name: `MSFT-ClientCAB-1` (deployment scripts resolve and verify its ID at runtime)
- Proposed resource group: `rg-swingdesk-prod`
- Region: `eastus2`
- Access model: password-only application authentication over managed HTTPS
- Execution mode: automation source only; no Azure resources may be created in this work

## Architecture

- Azure Container Registry stores the application image.
- Azure Container Apps runs one always-on replica with external HTTPS ingress and health probes.
- First-run deployment creates supporting infrastructure, builds the application in ACR, and only then creates the Container App.
- A dedicated user-assigned managed identity pulls images from ACR using `AcrPull`; registry admin credentials remain disabled.
- Azure Files mounts persistent application data at `/data` for settings, trade state, and the dashboard password hash.
- Container App secrets hold the dashboard password, session secret, and Coinbase credentials; secrets are supplied through an owner-only temporary parameters file that is always removed.
- GitHub Actions uses workload identity federation (OIDC), never a stored Azure client secret.

## Planned Artifacts

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
- No live Azure deployment or resource-state checks in this preparation-only run

## Deployment Gate

Azure deployment remains blocked until the user explicitly authorizes resource creation after reviewing validation output, expected cost, tenant, subscription, resource group, and region.
