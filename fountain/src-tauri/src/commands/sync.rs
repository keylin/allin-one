use crate::config::{AppSettings, SyncPlatformStatus, SyncState};
use crate::sync;
use crate::sync::api_client::SyncError;
use crate::sync::apple_books::BookManifestEntry;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tauri::{command, AppHandle, Emitter};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_store::StoreExt;

const SETTINGS_STORE: &str = "settings.json";
const SETTINGS_KEY: &str = "app_settings";
const SYNC_STATE_KEY: &str = "sync_state";
const APPLE_BOOKS_MANIFEST_KEY: &str = "apple_books_manifest";

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Platform {
    AppleBooks,
    WechatRead,
    Bilibili,
    Kindle,
    SafariBookmarks,
    ChromeBookmarks,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SyncResult {
    pub platform: Platform,
    pub success: bool,
    pub message: String,
    pub items_synced: u32,
}

/// Trigger sync for all enabled platforms
#[command]
pub async fn sync_now(app: AppHandle) -> Result<Vec<SyncResult>, String> {
    let settings = load_settings(&app)?;
    let mut results = Vec::new();

    if settings.apple_books_enabled {
        let r = run_apple_books_sync(&app, &settings).await;
        results.push(r);
    }
    if settings.wechat_read_enabled {
        let r = run_wechat_read_sync(&app, &settings).await;
        results.push(r);
    }
    if settings.bilibili_enabled {
        let r = run_bilibili_sync(&app, &settings).await;
        results.push(r);
    }
    if settings.kindle_enabled {
        let r = run_kindle_sync(&app, &settings).await;
        results.push(r);
    }
    if settings.safari_bookmarks_enabled {
        let r = run_safari_bookmarks_sync(&app, &settings).await;
        results.push(r);
    }
    if settings.chrome_bookmarks_enabled {
        let r = run_chrome_bookmarks_sync(&app, &settings).await;
        results.push(r);
    }

    Ok(results)
}

/// Trigger sync for a specific platform
#[command]
pub async fn sync_platform(app: AppHandle, platform: Platform) -> Result<SyncResult, String> {
    let settings = load_settings(&app)?;
    match platform {
        Platform::AppleBooks => Ok(run_apple_books_sync(&app, &settings).await),
        Platform::WechatRead => Ok(run_wechat_read_sync(&app, &settings).await),
        Platform::Bilibili => Ok(run_bilibili_sync(&app, &settings).await),
        Platform::Kindle => Ok(run_kindle_sync(&app, &settings).await),
        Platform::SafariBookmarks => Ok(run_safari_bookmarks_sync(&app, &settings).await),
        Platform::ChromeBookmarks => Ok(run_chrome_bookmarks_sync(&app, &settings).await),
    }
}

/// Get current sync state
#[command]
pub fn get_sync_status(app: AppHandle) -> Result<SyncState, String> {
    let store = app
        .store(SETTINGS_STORE)
        .map_err(|e| e.to_string())?;

    let state = store
        .get(SYNC_STATE_KEY)
        .and_then(|v| serde_json::from_value(v).ok())
        .unwrap_or_default();

    Ok(state)
}

fn load_settings(app: &AppHandle) -> Result<AppSettings, String> {
    let store = app
        .store(SETTINGS_STORE)
        .map_err(|e| e.to_string())?;

    Ok(match store.get(SETTINGS_KEY) {
        Some(v) => serde_json::from_value(v.clone()).unwrap_or_else(|e| {
            log::error!("sync::load_settings: deserialization failed: {e}");
            AppSettings::default()
        }),
        None => AppSettings::default(),
    })
}


pub(crate) async fn run_apple_books_sync(app: &AppHandle, settings: &AppSettings) -> SyncResult {
    update_platform_status(app, Platform::AppleBooks, SyncPlatformStatus::Syncing);

    let manifest = load_apple_books_manifest(app);
    let result = sync::apple_books::run_sync(settings, &manifest).await;
    match result {
        Ok((count, updated_manifest)) => {
            save_apple_books_manifest(app, &updated_manifest);
            update_platform_success(app, Platform::AppleBooks, count);
            if count > 0 && settings.notifications_enabled {
                let _ = app
                    .notification()
                    .builder()
                    .title("Apple Books Synced")
                    .body(format!("{} books synced successfully", count))
                    .show();
            }
            SyncResult {
                platform: Platform::AppleBooks,
                success: true,
                message: if count > 0 {
                    format!("Synced {} books", count)
                } else {
                    "No changes detected".to_string()
                },
                items_synced: count,
            }
        }
        Err(e) => {
            let msg = format!("{:#}", e);
            update_platform_error(app, Platform::AppleBooks, msg.clone());
            if settings.notifications_enabled {
                let _ = app
                    .notification()
                    .builder()
                    .title("Apple Books Sync Failed")
                    .body(&msg)
                    .show();
            }
            SyncResult {
                platform: Platform::AppleBooks,
                success: false,
                message: msg,
                items_synced: 0,
            }
        }
    }
}

fn load_apple_books_manifest(app: &AppHandle) -> HashMap<String, BookManifestEntry> {
    let store = match app.store(SETTINGS_STORE) {
        Ok(s) => s,
        Err(e) => {
            log::warn!("Failed to open settings store for manifest: {}", e);
            return HashMap::new();
        }
    };

    let Some(val) = store.get(APPLE_BOOKS_MANIFEST_KEY) else {
        return HashMap::new(); // first run
    };

    match serde_json::from_value(val) {
        Ok(manifest) => manifest,
        Err(e) => {
            log::warn!("Apple Books manifest corrupted, starting fresh ({})", e);
            HashMap::new()
        }
    }
}

fn save_apple_books_manifest(app: &AppHandle, manifest: &HashMap<String, BookManifestEntry>) {
    if let Ok(store) = app.store(SETTINGS_STORE) {
        if let Ok(val) = serde_json::to_value(manifest) {
            store.set(APPLE_BOOKS_MANIFEST_KEY, val);
            let _ = store.save();
        }
    }
}

pub(crate) async fn run_wechat_read_sync(app: &AppHandle, settings: &AppSettings) -> SyncResult {
    update_platform_status(app, Platform::WechatRead, SyncPlatformStatus::Syncing);

    let result = sync::wechat_read::run_sync(settings).await;
    match result {
        Ok(count) => {
            update_platform_success(app, Platform::WechatRead, count);
            if settings.notifications_enabled {
                let _ = app.notification()
                    .builder()
                    .title("微信读书已同步")
                    .body(format!("成功同步 {} 本书", count))
                    .show();
            }
            SyncResult {
                platform: Platform::WechatRead,
                success: true,
                message: format!("Synced {} books", count),
                items_synced: count,
            }
        }
        Err(e) => {
            handle_sync_error(app, settings, Platform::WechatRead, "微信读书", e)
        }
    }
}

pub(crate) async fn run_bilibili_sync(app: &AppHandle, settings: &AppSettings) -> SyncResult {
    update_platform_status(app, Platform::Bilibili, SyncPlatformStatus::Syncing);

    let result = sync::bilibili::run_sync(settings).await;
    match result {
        Ok(count) => {
            update_platform_success(app, Platform::Bilibili, count);
            if settings.notifications_enabled {
                let _ = app.notification()
                    .builder()
                    .title("Bilibili Synced")
                    .body(format!("{} videos synced successfully", count))
                    .show();
            }
            SyncResult {
                platform: Platform::Bilibili,
                success: true,
                message: format!("Synced {} videos", count),
                items_synced: count,
            }
        }
        Err(e) => {
            handle_sync_error(app, settings, Platform::Bilibili, "Bilibili", e)
        }
    }
}

pub(crate) async fn run_kindle_sync(app: &AppHandle, settings: &AppSettings) -> SyncResult {
    update_platform_status(app, Platform::Kindle, SyncPlatformStatus::Syncing);

    let result = sync::kindle::run_sync(settings).await;
    match result {
        Ok(count) => {
            update_platform_success(app, Platform::Kindle, count);
            if count > 0 && settings.notifications_enabled {
                let _ = app
                    .notification()
                    .builder()
                    .title("Kindle Synced")
                    .body(format!("{} books synced successfully", count))
                    .show();
            }
            SyncResult {
                platform: Platform::Kindle,
                success: true,
                message: if count > 0 {
                    format!("Synced {} books", count)
                } else {
                    "No new highlights".to_string()
                },
                items_synced: count,
            }
        }
        Err(e) => {
            handle_sync_error(app, settings, Platform::Kindle, "Kindle", e)
        }
    }
}

pub(crate) async fn run_safari_bookmarks_sync(
    app: &AppHandle,
    settings: &AppSettings,
) -> SyncResult {
    update_platform_status(app, Platform::SafariBookmarks, SyncPlatformStatus::Syncing);

    let result =
        sync::browser_bookmarks::run_sync(settings, sync::browser_bookmarks::Browser::Safari).await;
    match result {
        Ok(count) => {
            update_platform_success(app, Platform::SafariBookmarks, count);
            if count > 0 && settings.notifications_enabled {
                let _ = app
                    .notification()
                    .builder()
                    .title("Safari Bookmarks Synced")
                    .body(format!("{} bookmarks synced", count))
                    .show();
            }
            SyncResult {
                platform: Platform::SafariBookmarks,
                success: true,
                message: if count > 0 {
                    format!("Synced {} bookmarks", count)
                } else {
                    "No new bookmarks".to_string()
                },
                items_synced: count,
            }
        }
        Err(e) => {
            let msg = format!("{:#}", e);
            update_platform_error(app, Platform::SafariBookmarks, msg.clone());
            if settings.notifications_enabled {
                let _ = app
                    .notification()
                    .builder()
                    .title("Safari Bookmarks Sync Failed")
                    .body(&msg)
                    .show();
            }
            SyncResult {
                platform: Platform::SafariBookmarks,
                success: false,
                message: msg,
                items_synced: 0,
            }
        }
    }
}

pub(crate) async fn run_chrome_bookmarks_sync(
    app: &AppHandle,
    settings: &AppSettings,
) -> SyncResult {
    update_platform_status(app, Platform::ChromeBookmarks, SyncPlatformStatus::Syncing);

    let result =
        sync::browser_bookmarks::run_sync(settings, sync::browser_bookmarks::Browser::Chrome).await;
    match result {
        Ok(count) => {
            update_platform_success(app, Platform::ChromeBookmarks, count);
            if count > 0 && settings.notifications_enabled {
                let _ = app
                    .notification()
                    .builder()
                    .title("Chrome Bookmarks Synced")
                    .body(format!("{} bookmarks synced", count))
                    .show();
            }
            SyncResult {
                platform: Platform::ChromeBookmarks,
                success: true,
                message: if count > 0 {
                    format!("Synced {} bookmarks", count)
                } else {
                    "No new bookmarks".to_string()
                },
                items_synced: count,
            }
        }
        Err(e) => {
            let msg = format!("{:#}", e);
            update_platform_error(app, Platform::ChromeBookmarks, msg.clone());
            if settings.notifications_enabled {
                let _ = app
                    .notification()
                    .builder()
                    .title("Chrome Bookmarks Sync Failed")
                    .body(&msg)
                    .show();
            }
            SyncResult {
                platform: Platform::ChromeBookmarks,
                success: false,
                message: msg,
                items_synced: 0,
            }
        }
    }
}

/// Unified error handler for sync operations.
/// Checks if the error is a SyncError and uses its user-friendly message;
/// falls back to string matching for legacy anyhow errors.
fn handle_sync_error(
    app: &AppHandle,
    settings: &AppSettings,
    platform: Platform,
    platform_name: &str,
    error: anyhow::Error,
) -> SyncResult {
    // Try to downcast to SyncError for structured handling
    let (user_msg, needs_auth) = if let Some(sync_err) = error.downcast_ref::<SyncError>() {
        let needs_auth = matches!(sync_err, SyncError::AuthExpired(_));
        (sync_err.user_message().to_string(), needs_auth)
    } else {
        // Fallback: string-based detection for errors from anyhow/other sources
        // Fallback path: should not be reached once all sync modules return SyncError.
        let msg = format!("{:#}", error);
        let needs_auth = msg.contains("401") || msg.contains("expired");
        (msg, needs_auth)
    };

    log::error!("{} sync failed: {:#}", platform_name, error);

    if needs_auth {
        update_platform_status(app, platform.clone(), SyncPlatformStatus::NeedsAuth);
        if settings.notifications_enabled {
            let _ = app
                .notification()
                .builder()
                .title(&format!("{} 登录已过期", platform_name))
                .body(&user_msg)
                .show();
        }
    } else {
        update_platform_error(app, platform.clone(), user_msg.clone());
        if settings.notifications_enabled {
            let _ = app
                .notification()
                .builder()
                .title(&format!("{} 同步失败", platform_name))
                .body(&user_msg)
                .show();
        }
    }

    SyncResult {
        platform,
        success: false,
        message: user_msg,
        items_synced: 0,
    }
}

fn update_platform_status(app: &AppHandle, platform: Platform, status: SyncPlatformStatus) {
    if let Ok(store) = app.store(SETTINGS_STORE) {
        let mut state: SyncState = store
            .get(SYNC_STATE_KEY)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default();

        match platform {
            Platform::AppleBooks => state.apple_books_status = status,
            Platform::WechatRead => state.wechat_read_status = status,
            Platform::Bilibili => state.bilibili_status = status,
            Platform::Kindle => state.kindle_status = status,
            Platform::SafariBookmarks => state.safari_bookmarks_status = status,
            Platform::ChromeBookmarks => state.chrome_bookmarks_status = status,
        }

        if let Ok(val) = serde_json::to_value(&state) {
            store.set(SYNC_STATE_KEY, val);
            let _ = store.save();
        }
        // Emit event to frontend
        let _ = app.emit("sync-status-changed", &state);
    }
}

fn update_platform_success(app: &AppHandle, platform: Platform, count: u32) {
    if let Ok(store) = app.store(SETTINGS_STORE) {
        let mut state: SyncState = store
            .get(SYNC_STATE_KEY)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default();

        let now = chrono::Utc::now().to_rfc3339();
        match platform {
            Platform::AppleBooks => {
                state.apple_books_status = SyncPlatformStatus::Success;
                state.apple_books_last_sync = Some(now);
                state.apple_books_book_count += count;
                state.apple_books_error = None;
            }
            Platform::WechatRead => {
                state.wechat_read_status = SyncPlatformStatus::Success;
                state.wechat_read_last_sync = Some(now);
                state.wechat_read_book_count += count;
                state.wechat_read_error = None;
            }
            Platform::Bilibili => {
                state.bilibili_status = SyncPlatformStatus::Success;
                state.bilibili_last_sync = Some(now);
                state.bilibili_video_count += count;
                state.bilibili_error = None;
            }
            Platform::Kindle => {
                state.kindle_status = SyncPlatformStatus::Success;
                state.kindle_last_sync = Some(now);
                state.kindle_book_count += count;
                state.kindle_error = None;
            }
            Platform::SafariBookmarks => {
                state.safari_bookmarks_status = SyncPlatformStatus::Success;
                state.safari_bookmarks_last_sync = Some(now);
                state.safari_bookmarks_count += count;
                state.safari_bookmarks_error = None;
            }
            Platform::ChromeBookmarks => {
                state.chrome_bookmarks_status = SyncPlatformStatus::Success;
                state.chrome_bookmarks_last_sync = Some(now);
                state.chrome_bookmarks_count += count;
                state.chrome_bookmarks_error = None;
            }
        }

        if let Ok(val) = serde_json::to_value(&state) {
            store.set(SYNC_STATE_KEY, val);
            let _ = store.save();
        }
        let _ = app.emit("sync-status-changed", &state);
    }
}

/// On startup, reset any stale "Syncing" statuses left by a previous crash.
/// Called once before the scheduler starts.
pub(crate) fn reset_stale_sync_state(app: &AppHandle) {
    if let Ok(store) = app.store(SETTINGS_STORE) {
        let mut state: SyncState = store
            .get(SYNC_STATE_KEY)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default();

        let mut changed = false;
        if state.apple_books_status == SyncPlatformStatus::Syncing {
            state.apple_books_status = SyncPlatformStatus::Idle;
            changed = true;
        }
        if state.wechat_read_status == SyncPlatformStatus::Syncing {
            state.wechat_read_status = SyncPlatformStatus::Idle;
            changed = true;
        }
        if state.bilibili_status == SyncPlatformStatus::Syncing {
            state.bilibili_status = SyncPlatformStatus::Idle;
            changed = true;
        }
        if state.kindle_status == SyncPlatformStatus::Syncing {
            state.kindle_status = SyncPlatformStatus::Idle;
            changed = true;
        }
        if state.safari_bookmarks_status == SyncPlatformStatus::Syncing {
            state.safari_bookmarks_status = SyncPlatformStatus::Idle;
            changed = true;
        }
        if state.chrome_bookmarks_status == SyncPlatformStatus::Syncing {
            state.chrome_bookmarks_status = SyncPlatformStatus::Idle;
            changed = true;
        }

        if changed {
            if let Ok(val) = serde_json::to_value(&state) {
                store.set(SYNC_STATE_KEY, val);
                let _ = store.save();
            }
            log::info!("Reset stale Syncing statuses to Idle on startup");
        }
    }
}

fn update_platform_error(app: &AppHandle, platform: Platform, error: String) {
    if let Ok(store) = app.store(SETTINGS_STORE) {
        let mut state: SyncState = store
            .get(SYNC_STATE_KEY)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default();

        match platform {
            Platform::AppleBooks => {
                state.apple_books_status = SyncPlatformStatus::Error;
                state.apple_books_error = Some(error);
            }
            Platform::WechatRead => {
                state.wechat_read_status = SyncPlatformStatus::Error;
                state.wechat_read_error = Some(error);
            }
            Platform::Bilibili => {
                state.bilibili_status = SyncPlatformStatus::Error;
                state.bilibili_error = Some(error);
            }
            Platform::Kindle => {
                state.kindle_status = SyncPlatformStatus::Error;
                state.kindle_error = Some(error);
            }
            Platform::SafariBookmarks => {
                state.safari_bookmarks_status = SyncPlatformStatus::Error;
                state.safari_bookmarks_error = Some(error);
            }
            Platform::ChromeBookmarks => {
                state.chrome_bookmarks_status = SyncPlatformStatus::Error;
                state.chrome_bookmarks_error = Some(error);
            }
        }

        if let Ok(val) = serde_json::to_value(&state) {
            store.set(SYNC_STATE_KEY, val);
            let _ = store.save();
        }
        let _ = app.emit("sync-status-changed", &state);
    }
}
