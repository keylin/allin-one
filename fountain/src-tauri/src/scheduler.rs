use crate::config::AppSettings;
use log::info;
use std::sync::Arc;
use tauri::AppHandle;
use tokio::sync::{oneshot, RwLock};
use tokio::time::{interval, Duration};

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
        // Check every 5 minutes if any sync is due
        let mut tick = interval(Duration::from_secs(300));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let mut apple_books_last: Option<std::time::Instant> = None;
        let mut wechat_read_last: Option<std::time::Instant> = None;
        let mut bilibili_last: Option<std::time::Instant> = None;
        let mut kindle_last: Option<std::time::Instant> = None;
        let mut safari_bookmarks_last: Option<std::time::Instant> = None;
        let mut chrome_bookmarks_last: Option<std::time::Instant> = None;

        loop {
            tokio::select! {
                biased;

                // Shutdown signal takes priority — stop immediately
                _ = &mut shutdown => {
                    info!("Scheduler received shutdown signal, stopping");
                    break;
                }

                _ = tick.tick() => {
                    let settings = self.settings.read().await.clone();
                    let now = std::time::Instant::now();

                    if settings.apple_books_enabled {
                        let secs = settings.apple_books_interval_hours as u64 * 3600;
                        let due = apple_books_last
                            .map(|last| now.duration_since(last).as_secs() >= secs)
                            .unwrap_or(true);
                        if due {
                            info!("Scheduled: Apple Books sync starting");
                            let result = crate::commands::sync::run_apple_books_sync(
                                &self.app_handle,
                                &settings,
                            )
                            .await;
                            if result.success {
                                info!("Scheduled: Apple Books done ({} books)", result.items_synced);
                            } else {
                                log::error!("Scheduled: Apple Books failed: {}", result.message);
                            }
                            apple_books_last = Some(std::time::Instant::now());
                        }
                    }

                    if settings.wechat_read_enabled {
                        let secs = settings.wechat_read_interval_hours as u64 * 3600;
                        let due = wechat_read_last
                            .map(|last| now.duration_since(last).as_secs() >= secs)
                            .unwrap_or(true);
                        if due {
                            info!("Scheduled: WeChat Read sync starting");
                            let result = crate::commands::sync::run_wechat_read_sync(
                                &self.app_handle,
                                &settings,
                            )
                            .await;
                            if result.success {
                                info!("Scheduled: WeChat Read done ({} books)", result.items_synced);
                            } else {
                                log::error!("Scheduled: WeChat Read failed: {}", result.message);
                            }
                            wechat_read_last = Some(std::time::Instant::now());
                        }
                    }

                    if settings.bilibili_enabled {
                        let secs = settings.bilibili_interval_hours as u64 * 3600;
                        let due = bilibili_last
                            .map(|last| now.duration_since(last).as_secs() >= secs)
                            .unwrap_or(true);
                        if due {
                            info!("Scheduled: Bilibili sync starting");
                            let result = crate::commands::sync::run_bilibili_sync(
                                &self.app_handle,
                                &settings,
                            )
                            .await;
                            if result.success {
                                info!("Scheduled: Bilibili done ({} videos)", result.items_synced);
                            } else {
                                log::error!("Scheduled: Bilibili failed: {}", result.message);
                            }
                            bilibili_last = Some(std::time::Instant::now());
                        }
                    }

                    if settings.kindle_enabled {
                        let secs = settings.kindle_interval_hours as u64 * 3600;
                        let due = kindle_last
                            .map(|last| now.duration_since(last).as_secs() >= secs)
                            .unwrap_or(true);
                        if due {
                            info!("Scheduled: Kindle sync starting");
                            let result = crate::commands::sync::run_kindle_sync(
                                &self.app_handle,
                                &settings,
                            )
                            .await;
                            if result.success {
                                info!("Scheduled: Kindle done ({} books)", result.items_synced);
                            } else {
                                log::error!("Scheduled: Kindle failed: {}", result.message);
                            }
                            kindle_last = Some(std::time::Instant::now());
                        }
                    }

                    if settings.safari_bookmarks_enabled {
                        let secs = settings.bookmarks_interval_hours as u64 * 3600;
                        let due = safari_bookmarks_last
                            .map(|last| now.duration_since(last).as_secs() >= secs)
                            .unwrap_or(true);
                        if due {
                            info!("Scheduled: Safari bookmarks sync starting");
                            let result = crate::commands::sync::run_safari_bookmarks_sync(
                                &self.app_handle,
                                &settings,
                            )
                            .await;
                            if result.success {
                                info!(
                                    "Scheduled: Safari bookmarks done ({} bookmarks)",
                                    result.items_synced
                                );
                            } else {
                                log::error!("Scheduled: Safari bookmarks failed: {}", result.message);
                            }
                            safari_bookmarks_last = Some(std::time::Instant::now());
                        }
                    }

                    if settings.chrome_bookmarks_enabled {
                        let secs = settings.bookmarks_interval_hours as u64 * 3600;
                        let due = chrome_bookmarks_last
                            .map(|last| now.duration_since(last).as_secs() >= secs)
                            .unwrap_or(true);
                        if due {
                            info!("Scheduled: Chrome bookmarks sync starting");
                            let result = crate::commands::sync::run_chrome_bookmarks_sync(
                                &self.app_handle,
                                &settings,
                            )
                            .await;
                            if result.success {
                                info!(
                                    "Scheduled: Chrome bookmarks done ({} bookmarks)",
                                    result.items_synced
                                );
                            } else {
                                log::error!("Scheduled: Chrome bookmarks failed: {}", result.message);
                            }
                            chrome_bookmarks_last = Some(std::time::Instant::now());
                        }
                    }
                }
            }
        }
    }
}
