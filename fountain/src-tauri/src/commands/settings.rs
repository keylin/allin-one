use crate::config::AppSettings;
use crate::credential_store;
use serde::{Deserialize, Serialize};
use tauri::{command, AppHandle, Emitter};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_store::StoreExt;

const SETTINGS_STORE: &str = "settings.json";
const SETTINGS_KEY: &str = "app_settings";

#[derive(Debug, Serialize, Deserialize)]
pub struct ConnectionTestResult {
    pub ok: bool,
    pub message: String,
}

#[command]
pub fn get_settings(app: AppHandle) -> Result<AppSettings, String> {
    let store = app.store(SETTINGS_STORE).map_err(|e| e.to_string())?;
    let settings = store
        .get(SETTINGS_KEY)
        .and_then(|v| serde_json::from_value(v).ok())
        .unwrap_or_default();
    Ok(settings)
}

#[command]
pub fn save_settings(app: AppHandle, settings: AppSettings) -> Result<(), String> {
    let store = app.store(SETTINGS_STORE).map_err(|e| e.to_string())?;

    let val = serde_json::to_value(&settings).map_err(|e| e.to_string())?;
    store.set(SETTINGS_KEY, val.clone());
    store.save().map_err(|e| e.to_string())?;

    // Save API key to Keychain
    if !settings.api_key.is_empty() {
        credential_store::set_credential(credential_store::KEY_API_KEY, &settings.api_key)
            .map_err(|e| e.to_string())?;
    }

    // Apply autostart setting
    let autostart = app.autolaunch();
    if settings.autostart {
        autostart.enable().map_err(|e| e.to_string())?;
    } else {
        autostart.disable().map_err(|e| e.to_string())?;
    }

    // Notify scheduler of settings change
    if let Ok(json) = serde_json::to_string(&settings) {
        let _ = app.emit("settings-changed", json);
    }

    Ok(())
}

#[command]
pub async fn test_server_connection(
    server_url: String,
    api_key: String,
) -> Result<ConnectionTestResult, String> {
    let url = format!("{}/api/health", server_url.trim_end_matches('/'));
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| e.to_string())?;

    let mut req = client.get(&url);
    if !api_key.is_empty() {
        req = req.header("X-API-Key", &api_key);
    }

    match req.send().await {
        Ok(resp) => {
            if resp.status().is_success() {
                Ok(ConnectionTestResult {
                    ok: true,
                    message: format!("Connected ({})", resp.status()),
                })
            } else {
                Ok(ConnectionTestResult {
                    ok: false,
                    message: format!("Server returned {}", resp.status()),
                })
            }
        }
        Err(e) => Ok(ConnectionTestResult {
            ok: false,
            message: e.to_string(),
        }),
    }
}
