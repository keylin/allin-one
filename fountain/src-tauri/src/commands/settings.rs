use crate::config::AppSettings;
use crate::credential_store;
use serde::{Deserialize, Serialize};
use tauri::webview::WebviewWindowBuilder;
use tauri::{command, AppHandle, Emitter, Manager};
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
pub async fn open_settings_window(app: AppHandle) -> Result<(), String> {
    // Hide the popover so it doesn't cover the settings window
    if let Some(main_win) = app.get_webview_window("main") {
        let _ = main_win.hide();
    }

    if let Some(existing) = app.get_webview_window("settings") {
        let _ = existing.show();
        let _ = existing.set_focus();
        return Ok(());
    }

    WebviewWindowBuilder::new(
        &app,
        "settings",
        tauri::WebviewUrl::App("index.html#/settings".into()),
    )
    .title("Settings")
    .inner_size(560.0, 600.0)
    .resizable(false)
    .center()
    .build()
    .map_err(|e| e.to_string())?;

    Ok(())
}

#[command]
pub fn get_settings(app: AppHandle) -> Result<AppSettings, String> {
    let store = app.store(SETTINGS_STORE).map_err(|e| e.to_string())?;
    let settings = match store.get(SETTINGS_KEY) {
        Some(v) => match serde_json::from_value::<AppSettings>(v.clone()) {
            Ok(s) => s,
            Err(e) => {
                log::error!("Failed to deserialize app_settings from store: {e}. Raw JSON: {v}");
                AppSettings::default()
            }
        },
        None => {
            log::info!("No app_settings found in store, using defaults");
            AppSettings::default()
        }
    };
    Ok(settings)
}

#[command]
pub fn save_settings(app: AppHandle, settings: AppSettings) -> Result<(), String> {
    log::debug!("save_settings called: apple_books_enabled={}", settings.apple_books_enabled);
    let store = app.store(SETTINGS_STORE).map_err(|e| e.to_string())?;

    let val = serde_json::to_value(&settings).map_err(|e| e.to_string())?;
    store.set(SETTINGS_KEY, val);
    store.save().map_err(|e| {
        log::error!("Failed to save store to disk: {e}");
        e.to_string()
    })?;
    log::info!("Settings saved to store successfully");

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

    // Notify scheduler of settings change (emit struct directly to avoid double serialization)
    let _ = app.emit("settings-changed", &settings);

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
