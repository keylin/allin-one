use crate::config::AppSettings;
use log::info;
use std::sync::Arc;
use tauri::AppHandle;
use tokio::sync::{oneshot, RwLock};
use tokio::time::{interval, Duration};

/// Per-platform failure tracking for adaptive backoff.
struct PlatformState {
    last_run: Option<std::time::Instant>,
    consecutive_failures: u32,
}

impl PlatformState {
    fn new() -> Self {
        Self {
            last_run: None,
            consecutive_failures: 0,
        }
    }

    /// Check if sync is due, accounting for failure backoff.
    /// 3 consecutive failures → 2x interval; 4+ failures → 4x interval (cap).
    fn is_due(&self, now: std::time::Instant, base_interval_secs: u64) -> bool {
        let multiplier = if self.consecutive_failures >= 3 {
            std::cmp::min(1u64 << (self.consecutive_failures - 2), 4)
        } else {
            1
        };
        let effective_secs = base_interval_secs * multiplier;
        self.last_run
            .map(|last| now.duration_since(last).as_secs() >= effective_secs)
            .unwrap_or(true)
    }

    fn on_success(&mut self) {
        self.last_run = Some(std::time::Instant::now());
        self.consecutive_failures = 0;
    }

    fn on_failure(&mut self, is_network_error: bool) {
        self.consecutive_failures += 1;
        // NetworkError: don't update last_run so next tick retries immediately
        if !is_network_error {
            self.last_run = Some(std::time::Instant::now());
        }
    }
}

pub struct Scheduler {
    app_handle: AppHandle,
    settings: Arc<RwLock<AppSettings>>,
}

impl Scheduler {
    pub fn new(app_handle: AppHandle, settings: Arc<RwLock<AppSettings>>) -> Self {
        Self { app_handle, settings }
    }

    pub fn settings(&self) -> Arc<RwLock<AppSettings>> {
        self.settings.clone()
    }

    pub async fn run(&self, mut shutdown: oneshot::Receiver<()>) {
        let mut tick = interval(Duration::from_secs(300));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

        let mut apple_books = PlatformState::new();
        let mut wechat_read = PlatformState::new();
        let mut bilibili = PlatformState::new();
        let mut kindle = PlatformState::new();
        let mut safari_bookmarks = PlatformState::new();
        let mut chrome_bookmarks = PlatformState::new();

        loop {
            tokio::select! {
                biased;

                _ = &mut shutdown => {
                    info!("Scheduler received shutdown signal, stopping");
                    break;
                }

                _ = tick.tick() => {
                    let settings = self.settings.read().await.clone();
                    let now = std::time::Instant::now();

                    if settings.server_url.is_empty() {
                        log::debug!("Server URL not configured, skipping all syncs");
                        continue;
                    }

                    if settings.apple_books_enabled {
                        let secs = settings.apple_books_interval_hours as u64 * 3600;
                        if apple_books.is_due(now, secs) {
                            info!("Scheduled: Apple Books sync starting");
                            let result = crate::commands::sync::run_apple_books_sync(
                                &self.app_handle, &settings,
                            ).await;
                            if result.success {
                                info!("Scheduled: Apple Books done ({} books)", result.items_synced);
                                apple_books.on_success();
                            } else {
                                log::error!("Scheduled: Apple Books failed: {}", result.message);
                                apple_books.on_failure(is_network_error(&result.message));
                            }
                        }
                    }

                    if settings.wechat_read_enabled {
                        let secs = settings.wechat_read_interval_hours as u64 * 3600;
                        if wechat_read.is_due(now, secs) {
                            info!("Scheduled: WeChat Read sync starting");
                            let result = crate::commands::sync::run_wechat_read_sync(
                                &self.app_handle, &settings,
                            ).await;
                            if result.success {
                                info!("Scheduled: WeChat Read done ({} books)", result.items_synced);
                                wechat_read.on_success();
                            } else {
                                log::error!("Scheduled: WeChat Read failed: {}", result.message);
                                wechat_read.on_failure(is_network_error(&result.message));
                            }
                        }
                    }

                    if settings.bilibili_enabled {
                        let secs = settings.bilibili_interval_hours as u64 * 3600;
                        if bilibili.is_due(now, secs) {
                            info!("Scheduled: Bilibili sync starting");
                            let result = crate::commands::sync::run_bilibili_sync(
                                &self.app_handle, &settings,
                            ).await;
                            if result.success {
                                info!("Scheduled: Bilibili done ({} videos)", result.items_synced);
                                bilibili.on_success();
                            } else {
                                log::error!("Scheduled: Bilibili failed: {}", result.message);
                                bilibili.on_failure(is_network_error(&result.message));
                            }
                        }
                    }

                    if settings.kindle_enabled {
                        let secs = settings.kindle_interval_hours as u64 * 3600;
                        if kindle.is_due(now, secs) {
                            info!("Scheduled: Kindle sync starting");
                            let result = crate::commands::sync::run_kindle_sync(
                                &self.app_handle, &settings,
                            ).await;
                            if result.success {
                                info!("Scheduled: Kindle done ({} books)", result.items_synced);
                                kindle.on_success();
                            } else {
                                log::error!("Scheduled: Kindle failed: {}", result.message);
                                kindle.on_failure(is_network_error(&result.message));
                            }
                        }
                    }

                    if settings.safari_bookmarks_enabled {
                        let secs = settings.bookmarks_interval_hours as u64 * 3600;
                        if safari_bookmarks.is_due(now, secs) {
                            info!("Scheduled: Safari bookmarks sync starting");
                            let result = crate::commands::sync::run_safari_bookmarks_sync(
                                &self.app_handle, &settings,
                            ).await;
                            if result.success {
                                info!("Scheduled: Safari bookmarks done ({} bookmarks)", result.items_synced);
                                safari_bookmarks.on_success();
                            } else {
                                log::error!("Scheduled: Safari bookmarks failed: {}", result.message);
                                safari_bookmarks.on_failure(is_network_error(&result.message));
                            }
                        }
                    }

                    if settings.chrome_bookmarks_enabled {
                        let secs = settings.bookmarks_interval_hours as u64 * 3600;
                        if chrome_bookmarks.is_due(now, secs) {
                            info!("Scheduled: Chrome bookmarks sync starting");
                            let result = crate::commands::sync::run_chrome_bookmarks_sync(
                                &self.app_handle, &settings,
                            ).await;
                            if result.success {
                                info!("Scheduled: Chrome bookmarks done ({} bookmarks)", result.items_synced);
                                chrome_bookmarks.on_success();
                            } else {
                                log::error!("Scheduled: Chrome bookmarks failed: {}", result.message);
                                chrome_bookmarks.on_failure(is_network_error(&result.message));
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Heuristic: check if the error message indicates a network error.
fn is_network_error(msg: &str) -> bool {
    msg.contains("network error")
        || msg.contains("connection")
        || msg.contains("timed out")
        || msg.contains("网络连接失败") // SyncError::NetworkError user_message
}
