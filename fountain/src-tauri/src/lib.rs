mod commands;
mod config;
mod credential_store;
mod scheduler;
mod sync;

use std::sync::Arc;
use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    App, Listener, Manager, WebviewUrl, WebviewWindowBuilder,
};
use tokio::sync::RwLock;

pub fn run() {
    env_logger::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::sync::sync_now,
            commands::sync::sync_platform,
            commands::sync::get_sync_status,
            commands::credentials::get_credential,
            commands::credentials::set_credential,
            commands::credentials::delete_credential,
            commands::credentials::validate_bilibili_cookie,
            commands::credentials::validate_wechat_read_cookie,
            commands::credentials::start_bilibili_qr_login,
            commands::credentials::poll_bilibili_qr_status,
            commands::settings::get_settings,
            commands::settings::save_settings,
            commands::settings::test_server_connection,
        ])
        .setup(|app| {
            setup_tray(app)?;
            setup_windows(app)?;
            start_scheduler(app);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn setup_tray(app: &mut App) -> tauri::Result<()> {
    let tray = TrayIconBuilder::with_id("main-tray")
        .tooltip("Fountain")
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                toggle_main_window(app);
            }
        })
        .build(app)?;

    let icon_bytes = include_bytes!("../icons/tray-icon.png");
    let img = tauri::image::Image::from_bytes(icon_bytes)?;
    tray.set_icon(Some(img))?;
    tray.set_icon_as_template(true)?;

    Ok(())
}

fn setup_windows(app: &mut App) -> tauri::Result<()> {
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("/".into()))
        .title("Fountain")
        .inner_size(360.0, 520.0)
        .resizable(false)
        .visible(false)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .build()?;

    WebviewWindowBuilder::new(app, "settings", WebviewUrl::App("/settings".into()))
        .title("Fountain — Settings")
        .inner_size(560.0, 600.0)
        .resizable(false)
        .visible(false)
        .center()
        .build()?;

    Ok(())
}

fn start_scheduler(app: &mut App) {
    use tauri_plugin_store::StoreExt;

    // Load initial settings from store
    let initial_settings = app
        .store("settings.json")
        .ok()
        .and_then(|s| s.get("app_settings"))
        .and_then(|v| serde_json::from_value(v).ok())
        .unwrap_or_default();

    let settings = Arc::new(RwLock::new(initial_settings));
    let app_handle = app.handle().clone();
    let sched = scheduler::Scheduler::new(app_handle, settings);

    // Listen for settings changes to update scheduler
    let app_handle = app.handle().clone();
    app_handle.listen("settings-changed", {
        let sched_settings = sched.settings();
        move |event: tauri::Event| {
            if let Ok(new_settings) = serde_json::from_str::<config::AppSettings>(
                event.payload(),
            ) {
                let sched_settings = sched_settings.clone();
                tokio::spawn(async move {
                    *sched_settings.write().await = new_settings;
                });
            }
        }
    });

    tokio::spawn(async move { sched.run().await });
}

fn toggle_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let visible = window.is_visible().unwrap_or(false);
        if visible {
            let _ = window.hide();
        } else {
            position_popover_near_tray(&window);
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

fn position_popover_near_tray(window: &tauri::WebviewWindow) {
    if let Some(monitor) = window.primary_monitor().ok().flatten() {
        let screen_size = monitor.size();
        let scale = monitor.scale_factor();
        let win_size = window.outer_size().unwrap_or(tauri::PhysicalSize::new(360, 520));

        let x = (screen_size.width as f64 / scale) as i32 - win_size.width as i32 - 16;
        let y = 24;

        let _ = window.set_position(tauri::PhysicalPosition::new(x, y));
    }
}
