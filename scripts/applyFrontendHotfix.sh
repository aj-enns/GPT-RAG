#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <component-root>"
  exit 2
fi

component_root="$1"

replace_exact() {
  local file="$1"
  local old="$2"
  local new="$3"
  local label="$4"

  if [ ! -f "$file" ]; then
    echo "  Skipped $label (file not found)."
    return
  fi

  local content
  content="$(cat "$file")"
  if [[ "$content" == *"$old"* ]]; then
    content="${content//$old/$new}"
    printf "%s" "$content" > "$file"
    echo "  Patched $label"
  else
    echo "  Skipped $label (expected block not found)."
  fi
}

echo "Applying GPT-RAG UI deployment hotfixes..."

appconfig_path="$component_root/connectors/appconfig.py"
old_appconfig='        except (ClientAuthenticationError, AzureError) as e:
            # Most common local dev issue: not logged in / no managed identity.
            logger.warning(
                "Azure App Configuration unavailable (auth/network). Running with env vars only. "
                "If using Azure CLI auth, run: az login. Error: %s",
                e,
            )
            self.client = {}'
new_appconfig='        except (ClientAuthenticationError, AzureError) as e:
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
                self.client = {}'
replace_exact "$appconfig_path" "$old_appconfig" "$new_appconfig" "connectors/appconfig.py"

telemetry_path="$component_root/telemetry.py"
old_telemetry='            # Still configure application logging defaults.
            try:
                Telemetry.configure_logging(config)
            except Exception:
                Telemetry.configure_basic(config)
            return'
new_telemetry='            # Do not install OpenTelemetry log handlers when telemetry is disabled.
            # Fall back to basic stdlib logging only.
            Telemetry.configure_basic(config)
            return'
replace_exact "$telemetry_path" "$old_telemetry" "$new_telemetry" "telemetry.py"

app_path="$component_root/app.py"
old_app='else:
    ENABLE_AUTHENTICATION = False
    if ALLOW_ANONYMOUS:
        logger.warning(
            "Authentication disabled: OAuth not configured; running in anonymous mode (ALLOW_ANONYMOUS=true)"
        )'
new_app='else:
    ENABLE_AUTHENTICATION = False
    if ALLOW_ANONYMOUS:
        # Avoid warning-level log emission during module import; some telemetry
        # handler combinations can crash startup at import time.
        pass'
replace_exact "$app_path" "$old_app" "$new_app" "app.py"
