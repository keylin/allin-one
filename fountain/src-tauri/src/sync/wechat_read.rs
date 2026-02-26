/// WeChat Reading (微信读书) sync — ported from scripts/wechat-read-sync.py
/// Uses wr_skey + wr_vid cookies stored in Keychain.
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const WEREAD_BASE: &str = "https://i.weread.qq.com";
const BATCH_SIZE: usize = 20;

pub async fn run_sync(settings: &AppSettings) -> Result<u32> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let skey = credential_store::get_credential(credential_store::KEY_WECHAT_READ_SKEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let vid = credential_store::get_credential(credential_store::KEY_WECHAT_READ_VID)
        .unwrap_or(None)
        .unwrap_or_default();

    if skey.is_empty() || vid.is_empty() {
        bail!("WeChat Read credentials not configured");
    }

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let api_client = ApiClient::new(settings.server_url.clone(), api_key);

    // Build WeChat Read HTTP client with cookies
    let cookie = format!("wr_skey={}; wr_vid={}", skey, vid);
    let mut default_headers = reqwest::header::HeaderMap::new();
    let cookie_val = reqwest::header::HeaderValue::try_from(cookie.as_str())
        .context("Invalid WeChat Read cookie format (non-ASCII characters in credentials)")?;
    default_headers.insert("Cookie", cookie_val);
    default_headers.insert(
        "User-Agent",
        reqwest::header::HeaderValue::from_static("WeRead/8.0 Mozilla/5.0"),
    );
    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .default_headers(default_headers)
        .build()?;

    // Fetch bookshelf
    let shelf_resp = http
        .get(format!("{}/shelf/friendCommon", WEREAD_BASE))
        .send()
        .await
        .context("WeChat Read shelf request failed")?;

    if shelf_resp.status() == 401 {
        bail!("WeChat Read auth expired (401)");
    }
    if !shelf_resp.status().is_success() {
        bail!("WeChat Read shelf error: {}", shelf_resp.status());
    }

    // Check for refreshed cookies in response headers
    let new_skey = extract_cookie_from_response(&shelf_resp, "wr_skey");
    if let Some(new_val) = new_skey {
        if let Err(e) = credential_store::set_credential(credential_store::KEY_WECHAT_READ_SKEY, &new_val) {
            log::warn!("Failed to refresh WeChat Read skey in Keychain: {}", e);
        }
    }

    let shelf: Value = shelf_resp.json().await?;
    let books = shelf["books"].as_array().cloned().unwrap_or_default();
    if books.is_empty() {
        return Ok(0);
    }

    // Three-step protocol
    let source_id = api_client
        .ebook_setup("sync.wechat_read")
        .await
        .context("ebook setup failed")?;

    let last_sync_at = api_client.ebook_status(&source_id).await.unwrap_or(None);
    let last_sync_ts: Option<i64> = last_sync_at
        .as_deref()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp());

    // Incremental: filter books updated after last_sync_at using their sort field
    // WeChat Read `books` array doesn't expose update time at shelf level,
    // so we sync all books but filter annotations by createTime.
    let mut total_synced = 0u32;
    let book_ids: Vec<String> = books
        .iter()
        .filter_map(|b| b["bookId"].as_str().map(|s| s.to_string()))
        .collect();

    for chunk in book_ids.chunks(BATCH_SIZE) {
        let mut ebooks = Vec::new();

        for book_id in chunk {
            let book_info = books
                .iter()
                .find(|b| b["bookId"].as_str() == Some(book_id));

            let Some(book) = book_info else { continue };

            // Fetch reading progress
            let progress_resp = http
                .get(format!("{}/book/progress", WEREAD_BASE))
                .query(&[("bookId", book_id.as_str())])
                .send()
                .await;

            let reading_progress = if let Ok(resp) = progress_resp {
                resp.json::<Value>()
                    .await
                    .ok()
                    .and_then(|v| v["progress"]["progress"].as_f64())
                    .map(|p| p / 100.0)
                    .unwrap_or(0.0)
            } else {
                0.0
            };

            // Fetch annotations for this book (incremental: filter by last_sync_ts)
            let annots = fetch_annotations(&http, book_id, last_sync_ts).await.unwrap_or_default();

            ebooks.push(json!({
                "external_id": book_id,
                "title": book["title"].as_str().unwrap_or(""),
                "author": book["author"].as_str().unwrap_or(""),
                "cover_url": book["cover"].as_str(),
                "reading_progress": reading_progress,
                "source_id": source_id,
                "annotations": annots,
            }));
        }

        if !ebooks.is_empty() {
            let payload = json!({
                "source_id": source_id,
                "ebooks": ebooks,
            });
            api_client.ebook_sync(payload).await.context("ebook sync failed")?;
            total_synced += ebooks.len() as u32;
        }

        // Respect API rate limits
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }

    Ok(total_synced)
}

async fn fetch_annotations(http: &reqwest::Client, book_id: &str, since_ts: Option<i64>) -> Result<Vec<Value>> {
    let resp = http
        .get(format!("{}/book/bookmarklist", WEREAD_BASE))
        .query(&[("bookId", book_id)])
        .send()
        .await?;

    if !resp.status().is_success() {
        return Ok(vec![]);
    }

    let data: Value = resp.json().await?;
    let bookmarks = data["updated"].as_array().cloned().unwrap_or_default();

    // Filter by since_ts for incremental sync
    let bookmarks: Vec<_> = bookmarks
        .into_iter()
        .filter(|b| {
            if let Some(since) = since_ts {
                b["createTime"].as_i64().map(|t| t > since).unwrap_or(true)
            } else {
                true
            }
        })
        .collect();

    let annotations: Vec<Value> = bookmarks
        .iter()
        .map(|b| {
            let color_name = match b["colorStyle"].as_i64().unwrap_or(0) {
                1 => "yellow",
                2 => "blue",
                3 => "pink",
                4 => "green",
                _ => "yellow",
            };

            let annot_type = if b["type"].as_i64().unwrap_or(1) == 1 {
                "highlight"
            } else {
                "note"
            };

            let created_at = b["createTime"].as_i64().map(|ts| {
                chrono::DateTime::from_timestamp(ts, 0)
                    .map(|dt| dt.to_rfc3339())
                    .unwrap_or_default()
            });

            json!({
                "id": b["bookmarkId"].as_str().unwrap_or(""),
                "selected_text": b["markText"].as_str(),
                "note": b["review"]["content"].as_str(),
                "color": color_name,
                "type": annot_type,
                "chapter": b["chapterTitle"].as_str(),
                "created_at": created_at,
            })
        })
        .collect();

    Ok(annotations)
}

fn extract_cookie_from_response(resp: &reqwest::Response, cookie_name: &str) -> Option<String> {
    for header in resp.headers().get_all("set-cookie") {
        if let Ok(s) = header.to_str() {
            for part in s.split(';') {
                let kv: Vec<&str> = part.trim().splitn(2, '=').collect();
                if kv.len() == 2 && kv[0].trim() == cookie_name {
                    return Some(kv[1].trim().to_string());
                }
            }
        }
    }
    None
}
