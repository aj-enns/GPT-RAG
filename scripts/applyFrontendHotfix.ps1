param(
  [Parameter(Mandatory = $false)]
  [string]$ComponentRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# If ComponentRoot not provided, try to derive it from the script location or caller's context
if ([string]::IsNullOrWhiteSpace($ComponentRoot)) {
  # Try to find the gpt-rag-ui folder in sibling repos (common pattern)
  $parent = Split-Path -Parent $PSScriptRoot
  $candidate = Join-Path $parent 'gpt-rag-ui'
  if (Test-Path -LiteralPath $candidate) {
    $ComponentRoot = $candidate
    Write-Host "ComponentRoot auto-detected: $ComponentRoot" -ForegroundColor Gray
  } else {
    Write-Host "  ⚠️  ComponentRoot not provided and gpt-rag-ui sibling not found; skipping hotfixes." -ForegroundColor Yellow
    exit 0
  }
}

Write-Host "Using ComponentRoot: $ComponentRoot" -ForegroundColor Gray

function Update-ExactBlock {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Old,
    [Parameter(Mandatory = $true)][string]$New,
    [Parameter(Mandatory = $true)][string]$Label
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    Write-Host "  Skipped $Label (file not found)." -ForegroundColor Yellow
    return
  }

  $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  if ($content.Contains($Old)) {
    $content = $content.Replace($Old, $New)
    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
    Write-Host "  Patched $Label" -ForegroundColor Green
  } else {
    Write-Host "  Skipped $Label (expected block not found)." -ForegroundColor Yellow
  }
}

Write-Host "Applying GPT-RAG UI deployment hotfixes..." -ForegroundColor Cyan

$appconfigPath = Join-Path $ComponentRoot 'connectors\appconfig.py'

# Hotfix: normalize invalid AZURE_CLIENT_ID="*" (default when unset) to None so
# ManagedIdentityCredential picks up the SystemAssigned identity instead of failing
# with "invalid_scope". Required when Container App uses SystemAssigned identity.
$oldClientId = @"
        try:
            self.client_id = os.environ.get('AZURE_CLIENT_ID', "*")
        except Exception as e:
            raise e
"@
$newClientId = @"
        try:
            _cid = os.environ.get('AZURE_CLIENT_ID', "*")
            # Treat sentinel "*" or empty as unset (SystemAssigned identity).
            self.client_id = _cid if _cid and _cid != "*" else None
        except Exception as e:
            raise e
"@
Update-ExactBlock -Path $appconfigPath -Old $oldClientId -New $newClientId -Label 'connectors/appconfig.py (client_id normalize)'

$oldAppConfig = @"
        except (ClientAuthenticationError, AzureError) as e:
            # Most common local dev issue: not logged in / no managed identity.
            logger.warning(
                "Azure App Configuration unavailable (auth/network). Running with env vars only. "
                "If using Azure CLI auth, run: az login. Error: %s",
                e,
            )
            self.client = {}
"@
$newAppConfig = @"
        except (ClientAuthenticationError, AzureError) as e:
            # Most common issue: managed identity / auth / transient network failures.
            # Try connection string fallback before dropping to env-only mode.
            logger.warning(
                "Unable to connect to Azure App Configuration endpoint; trying connection string (if set). Error: %s",
                e,
            )
            try:
                connection_string = os.environ["AZURE_APPCONFIG_CONNECTION_STRING"]
                self.client = load(
                    connection_string=connection_string,
                    key_vault_options=AzureAppConfigurationKeyVaultOptions(credential=self.credential),
                )
                self.connected = True
                logger.info("Azure App Configuration loaded using AZURE_APPCONFIG_CONNECTION_STRING fallback")
            except Exception as e2:
                logger.warning(
                    "Azure App Configuration connection string not available/failed; running with env vars only. Error: %s",
                    e2,
                )
                self.client = {}
"@
Update-ExactBlock -Path $appconfigPath -Old $oldAppConfig -New $newAppConfig -Label 'connectors/appconfig.py'

$telemetryPath = Join-Path $ComponentRoot 'telemetry.py'
$oldTelemetry = @"
            # Still configure application logging defaults.
            try:
                Telemetry.configure_logging(config)
            except Exception:
                Telemetry.configure_basic(config)
            return
"@
$newTelemetry = @"
            # Do not install OpenTelemetry log handlers when telemetry is disabled.
            # Fall back to basic stdlib logging only.
            Telemetry.configure_basic(config)
            return
"@
Update-ExactBlock -Path $telemetryPath -Old $oldTelemetry -New $newTelemetry -Label 'telemetry.py'

$appPath = Join-Path $ComponentRoot 'app.py'
$oldApp = @"
else:
    ENABLE_AUTHENTICATION = False
    if ALLOW_ANONYMOUS:
        logger.warning(
            "Authentication disabled: OAuth not configured; running in anonymous mode (ALLOW_ANONYMOUS=true)"
        )
"@
$newApp = @"
else:
    ENABLE_AUTHENTICATION = False
    if ALLOW_ANONYMOUS:
        # Avoid warning-level log emission during module import; some telemetry
        # handler combinations can crash startup at import time.
        pass
"@
Update-ExactBlock -Path $appPath -Old $oldApp -New $newApp -Label 'app.py'
