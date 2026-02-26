/// Browser bookmarks sync — reads Safari (plist) and Chrome (JSON) bookmarks
/// and pushes them to the Allin-One backend.
///
/// Safari:  ~/Library/Safari/Bookmarks.plist
///          Reading List node → "com.apple.ReadingList"
/// Chrome:  ~/Library/Application Support/Google/Chrome/Default/Bookmarks
///          (JSON, "roots" → "bookmark_bar", "other", "synced")
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::path::PathBuf;

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const BATCH_SIZE: usize = 100;

#[derive(Debug)]
pub struct Bookmark {
    pub url: String,
    pub title: String,
    pub folder: Option<String>,
    pub added_at: Option<String>,
}

/// Which browser to sync
#[derive(Debug, Clone, PartialEq)]
pub enum Browser {
    Safari,
    Chrome,
}

/// Run bookmark sync for the specified browser.
/// Returns the number of bookmarks pushed.
pub async fn run_sync(settings: &AppSettings, browser: Browser) -> Result<u32> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let client = ApiClient::new(settings.server_url.clone(), api_key);

    let source_type = match browser {
        Browser::Safari => "sync.safari_bookmarks",
        Browser::Chrome => "sync.chrome_bookmarks",
    };

    let source_id = client
        .bookmark_setup(source_type)
        .await
        .context("bookmark setup failed")?;

    let last_sync_at = client.bookmark_status(&source_id).await?;
    let last_sync_ts = last_sync_at
        .as_deref()
        .and_then(parse_iso_to_timestamp);

    let bookmarks = match browser {
        Browser::Safari => read_safari_bookmarks(settings)?,
        Browser::Chrome => read_chrome_bookmarks(settings)?,
    };

    if bookmarks.is_empty() {
        return Ok(0);
    }

    // Incremental: only push bookmarks added after last sync
    let to_push: Vec<&Bookmark> = bookmarks
        .iter()
        .filter(|bm| {
            if last_sync_ts.is_none() {
                return true;
            }
            let threshold = last_sync_ts.unwrap();
            bm.added_at
                .as_deref()
                .and_then(parse_iso_to_timestamp)
                .map(|ts| ts > threshold)
                .unwrap_or(true) // push if no timestamp (first run)
        })
        .collect();

    if to_push.is_empty() {
        return Ok(0);
    }

    let mut total_pushed = 0u32;

    for chunk in to_push.chunks(BATCH_SIZE) {
        let bm_values: Vec<Value> = chunk
            .iter()
            .map(|bm| json!({
                "url": bm.url,
                "title": bm.title,
                "folder": bm.folder,
                "added_at": bm.added_at,
            }))
            .collect();

        let payload = json!({
            "source_id": source_id,
            "bookmarks": bm_values,
        });

        client
            .bookmark_sync(payload)
            .await
            .context("bookmark sync batch failed")?;

        total_pushed += chunk.len() as u32;
    }

    Ok(total_pushed)
}

// ─── Safari ───────────────────────────────────────────────────────────────────

fn read_safari_bookmarks(settings: &AppSettings) -> Result<Vec<Bookmark>> {
    let path = safari_bookmarks_path(settings)?;
    let plist_value: plist::Value = plist::from_file(&path)
        .with_context(|| format!("Failed to read Safari bookmarks plist: {:?}", path))?;

    let mut results = Vec::new();
    if let plist::Value::Dictionary(root) = plist_value {
        if let Some(plist::Value::Array(children)) = root.get("Children") {
            for child in children {
                collect_safari_bookmarks(child, None, &mut results);
            }
        }
    }

    Ok(results)
}

fn collect_safari_bookmarks(
    node: &plist::Value,
    folder_path: Option<&str>,
    results: &mut Vec<Bookmark>,
) {
    let plist::Value::Dictionary(dict) = node else {
        return;
    };

    let web_type = dict
        .get("WebBookmarkType")
        .and_then(|v| v.as_string())
        .unwrap_or("");

    match web_type {
        "WebBookmarkTypeLeaf" => {
            // Regular bookmark
            let url = dict
                .get("URLString")
                .and_then(|v| v.as_string())
                .unwrap_or("")
                .to_string();

            if url.is_empty() || url.starts_with("javascript:") {
                return;
            }

            let title = dict
                .get("URIDictionary")
                .and_then(|v| v.as_dictionary())
                .and_then(|d| d.get("title"))
                .and_then(|v| v.as_string())
                .unwrap_or(&url)
                .to_string();

            // Reading list entry has extra metadata (DateAdded as ISO string in plist)
            let added_at = dict
                .get("ReadingList")
                .and_then(|v| v.as_dictionary())
                .and_then(|d| d.get("DateAdded"))
                .and_then(|v| v.as_date())
                .map(plist_date_to_iso);

            results.push(Bookmark {
                url,
                title,
                folder: folder_path.map(|s| s.to_string()),
                added_at,
            });
        }
        "WebBookmarkTypeList" => {
            // Folder — recurse
            let folder_title = dict
                .get("Title")
                .and_then(|v| v.as_string())
                .unwrap_or("");

            // Skip the root "BookmarksBar", "BookmarksMenu" wrappers (but keep their children)
            let new_path = match folder_path {
                None => {
                    if folder_title.is_empty() || folder_title == "BookmarksBar" || folder_title == "BookmarksMenu" {
                        None
                    } else {
                        Some(folder_title.to_string())
                    }
                }
                Some(parent) => {
                    if folder_title.is_empty() {
                        Some(parent.to_string())
                    } else {
                        Some(format!("{}/{}", parent, folder_title))
                    }
                }
            };

            if let Some(plist::Value::Array(children)) = dict.get("Children") {
                for child in children {
                    collect_safari_bookmarks(child, new_path.as_deref(), results);
                }
            }
        }
        _ => {}
    }
}

fn safari_bookmarks_path(settings: &AppSettings) -> Result<PathBuf> {
    if let Some(custom) = &settings.safari_bookmarks_path {
        let p = PathBuf::from(custom);
        if p.exists() {
            return Ok(p);
        }
    }

    #[cfg(target_os = "macos")]
    {
        let home = std::env::var("HOME").context("HOME not set")?;
        let p = PathBuf::from(home).join("Library/Safari/Bookmarks.plist");
        if p.exists() {
            return Ok(p);
        }
        bail!("Safari Bookmarks.plist not found at {:?}", p);
    }

    #[cfg(not(target_os = "macos"))]
    bail!("Safari bookmarks are only available on macOS");
}

// ─── Chrome ───────────────────────────────────────────────────────────────────

fn read_chrome_bookmarks(settings: &AppSettings) -> Result<Vec<Bookmark>> {
    let path = chrome_bookmarks_path(settings)?;
    let data = std::fs::read_to_string(&path)
        .with_context(|| format!("Failed to read Chrome bookmarks: {:?}", path))?;
    let root: Value = serde_json::from_str(&data).context("Invalid Chrome bookmarks JSON")?;

    let mut results = Vec::new();
    if let Some(roots) = root.get("roots").and_then(|v| v.as_object()) {
        for (root_name, node) in roots {
            // Skip "sync_transaction_version" and similar metadata
            if !node.is_object() {
                continue;
            }
            collect_chrome_bookmarks(node, Some(root_name), &mut results);
        }
    }

    Ok(results)
}

fn collect_chrome_bookmarks(node: &Value, folder_path: Option<&str>, results: &mut Vec<Bookmark>) {
    let Some(obj) = node.as_object() else {
        return;
    };

    let node_type = obj.get("type").and_then(|v| v.as_str()).unwrap_or("");

    match node_type {
        "url" => {
            let url = obj
                .get("url")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            if url.is_empty() || url.starts_with("javascript:") || url.starts_with("chrome:") {
                return;
            }

            let title = obj
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or(&url)
                .to_string();

            // Chrome stores time as microseconds since Jan 1, 1601
            let added_at = obj
                .get("date_added")
                .and_then(|v| v.as_str())
                .and_then(|s| s.parse::<i64>().ok())
                .map(chrome_timestamp_to_iso);

            results.push(Bookmark {
                url,
                title,
                folder: folder_path.map(|s| s.to_string()),
                added_at,
            });
        }
        "folder" => {
            let name = obj.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let new_path = match folder_path {
                None => {
                    if name.is_empty() { None } else { Some(name.to_string()) }
                }
                Some(parent) => {
                    if name.is_empty() {
                        Some(parent.to_string())
                    } else {
                        Some(format!("{}/{}", parent, name))
                    }
                }
            };

            if let Some(Value::Array(children)) = obj.get("children") {
                for child in children {
                    collect_chrome_bookmarks(child, new_path.as_deref(), results);
                }
            }
        }
        _ => {}
    }
}

fn chrome_bookmarks_path(settings: &AppSettings) -> Result<PathBuf> {
    if let Some(custom) = &settings.chrome_bookmarks_path {
        let p = PathBuf::from(custom);
        if p.exists() {
            return Ok(p);
        }
    }

    #[cfg(target_os = "macos")]
    {
        let home = std::env::var("HOME").context("HOME not set")?;
        let candidates = [
            "Library/Application Support/Google/Chrome/Default/Bookmarks",
            "Library/Application Support/Google/Chrome Beta/Default/Bookmarks",
            "Library/Application Support/Chromium/Default/Bookmarks",
            "Library/Application Support/BraveSoftware/Brave-Browser/Default/Bookmarks",
            "Library/Application Support/Microsoft Edge/Default/Bookmarks",
        ];
        for candidate in &candidates {
            let p = PathBuf::from(&home).join(candidate);
            if p.exists() {
                return Ok(p);
            }
        }
        bail!("Chrome (or compatible) bookmarks file not found. Install Chrome or set a custom path in Settings.");
    }

    #[cfg(not(target_os = "macos"))]
    bail!("Chrome bookmarks auto-detection is only supported on macOS");
}

/// Convert Chrome's microseconds-since-1601 to ISO 8601 string.
fn chrome_timestamp_to_iso(micros: i64) -> String {
    // Chrome epoch: Jan 1, 1601; Unix epoch: Jan 1, 1970
    // Difference: 11644473600 seconds
    const CHROME_EPOCH_OFFSET_SECS: i64 = 11_644_473_600;
    let unix_secs = micros / 1_000_000 - CHROME_EPOCH_OFFSET_SECS;
    if unix_secs <= 0 {
        return String::new();
    }
    match chrono::DateTime::from_timestamp(unix_secs, 0) {
        Some(dt) => dt.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        None => String::new(),
    }
}

fn parse_iso_to_timestamp(s: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(s)
        .ok()
        .map(|dt| dt.timestamp())
}

/// Convert a plist Date value to an ISO 8601 string.
/// plist::Date stores seconds since 2001-01-01 (Apple's Core Data epoch).
fn plist_date_to_iso(date: plist::Date) -> String {
    // plist::Date implements Into<SystemTime>
    use std::time::SystemTime;
    let system_time: SystemTime = date.into();
    match system_time.duration_since(SystemTime::UNIX_EPOCH) {
        Ok(d) => {
            match chrono::DateTime::from_timestamp(d.as_secs() as i64, 0) {
                Some(dt) => dt.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
                None => String::new(),
            }
        }
        Err(_) => String::new(),
    }
}
