# GPT-RAG Canada Deployment Runbook

## Purpose

This runbook captures the exact changes used to deploy GPT-RAG in Canada, the differences from quick setup defaults, and the persistence changes added so future deployments keep working.

## What happened and why

### 1. Duplicate folder after azd init

Behavior observed:
- Running azd init -t in an existing repo created a nested scaffold folder.

Why:
- azd init template flow scaffolds into a new folder unless you explicitly initialize the current folder in a compatible state.

Action:
- Keep only one working repository root and remove the duplicate scaffold folder.

### 2. No subscription or region prompt

Behavior observed:
- azd did not prompt for subscription or location during the initial run.

Why:
- Existing azd environment context and local settings can bypass interactive prompts.

Action:
- Explicitly set the target location and environment values before provisioning.

## Canada-specific deployment decisions

### Primary region
- Deployment target: canadacentral

### Azure AI Search workaround region
- Search region override: canadaeast

Reason:
- Capacity limitations prevented successful provisioning in canadacentral for this deployment.

Implementation:
- Set AZURE_SEARCH_LOCATION=canadaeast for the deployment environment while keeping the main deployment in canadacentral.

### Model and SKU choices

Configured in main.parameters.json:
- Chat model:
  - name: gpt-5.4-nano
  - version: 2026-03-17
  - sku: GlobalStandard
  - capacity: 8
- Embedding model:
  - name: text-embedding-3-large
  - version: 1
  - sku: GlobalStandard
  - capacity: 8

Reason:
- Canada availability and quota/capacity constraints required a compatible model/version/SKU matrix and lower capacity.

## Runtime issue and fix

### Symptom
- Frontend returned not ready/503 even after deploy.

### Root cause
- Frontend could not reliably read Azure App Configuration using endpoint/managed identity path in this environment.
- Additional startup instability occurred when telemetry connection string was missing.

### Working runtime workaround
- Use AZURE_APPCONFIG_CONNECTION_STRING fallback path.
- Avoid OpenTelemetry log handler setup when telemetry is not configured.

## What was modified from quick setup

Quick setup expectation:
- Stock component versions from manifest deploy and run as-is.

Actual required changes:
1. Regional split for Search capacity:
- Keep core deployment in canadacentral.
- Override Search location to canadaeast.

2. Lower model capacity:
- Capacity reduced to 8 for both chat and embedding deployments.

3. Frontend startup hardening:
- App Config auth/network exception path now attempts connection string fallback.
- Telemetry disabled path now uses basic logging only.
- Anonymous mode import-time warning path suppressed to avoid startup crash in this environment.

## Persistence added to deployment pipeline

To avoid reapplying manual fixes after each azd deploy, this repository now auto-patches gpt-rag-ui during predeploy.

Added files:
- scripts/applyFrontendHotfix.ps1
- scripts/applyFrontendHotfix.sh

Updated files:
- scripts/preDeploy.ps1
- scripts/preDeploy.sh

Behavior:
- During component deployment, when the component name is gpt-rag-ui, the hotfix script runs before the child deploy script.
- The hotfix applies deterministic text patches to:
  - connectors/appconfig.py
  - telemetry.py
  - app.py

Result:
- Future azd deploy executions from this repo keep the frontend fix without requiring manual source edits in sibling component folders.

## Operational checklist

1. Confirm environment targets Canada:
- AZURE_LOCATION=canadacentral
- AZURE_SEARCH_LOCATION=canadaeast

2. Confirm modelDeploymentList in main.parameters.json matches Canada-tested values in this document.

3. Run deployment:
- azd provision
- azd deploy

4. Verify frontend health endpoint returns 200.

5. Verify frontend logs show App Config connection-string fallback success when endpoint auth fails.

## Notes for CI/CD

If your deployment pipeline runs on Linux, keep scripts/applyFrontendHotfix.sh available and executable in the repo.

If your deployment pipeline runs on Windows agents, scripts/applyFrontendHotfix.ps1 is used by default.

## Important warning

This is a compatibility workaround for the currently pinned frontend component behavior. Once upstream gpt-rag-ui includes these fixes in an official release tag, remove the hotfix scripts and consume the fixed tag in manifest.json.
