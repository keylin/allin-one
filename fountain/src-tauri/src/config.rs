use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppSettings {
    pub server_url: String,
    pub api_key: String,
    pub apple_books_enabled: bool,
    pub wechat_read_enabled: bool,
    pub bilibili_enabled: bool,
    pub apple_books_interval_hours: u32,
    pub wechat_read_interval_hours: u32,
    pub bilibili_interval_hours: u32,
    pub autostart: bool,
    pub notifications_enabled: bool,
    pub apple_books_db_path: Option<String>,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            server_url: String::new(),
            api_key: String::new(),
            apple_books_enabled: true,
            wechat_read_enabled: false,
            bilibili_enabled: false,
            apple_books_interval_hours: 6,
            wechat_read_interval_hours: 12,
            bilibili_interval_hours: 6,
            autostart: false,
            notifications_enabled: true,
            apple_books_db_path: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncState {
    pub apple_books_last_sync: Option<String>,
    pub wechat_read_last_sync: Option<String>,
    pub bilibili_last_sync: Option<String>,
    pub apple_books_book_count: u32,
    pub wechat_read_book_count: u32,
    pub bilibili_video_count: u32,
    pub apple_books_status: SyncPlatformStatus,
    pub wechat_read_status: SyncPlatformStatus,
    pub bilibili_status: SyncPlatformStatus,
    pub apple_books_error: Option<String>,
    pub wechat_read_error: Option<String>,
    pub bilibili_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum SyncPlatformStatus {
    Idle,
    Syncing,
    Success,
    Error,
    NeedsAuth,
}

impl Default for SyncState {
    fn default() -> Self {
        Self {
            apple_books_last_sync: None,
            wechat_read_last_sync: None,
            bilibili_last_sync: None,
            apple_books_book_count: 0,
            wechat_read_book_count: 0,
            bilibili_video_count: 0,
            apple_books_status: SyncPlatformStatus::Idle,
            wechat_read_status: SyncPlatformStatus::Idle,
            bilibili_status: SyncPlatformStatus::Idle,
            apple_books_error: None,
            wechat_read_error: None,
            bilibili_error: None,
        }
    }
}

