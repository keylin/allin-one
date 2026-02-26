/// Zhihu (知乎) favorites sync.
/// Uses z_c0 cookie stored in Keychain.
/// Fetches items from all private favorite folders → pushes to /api/bookmark/sync.
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const ZHIHU_API: &str = "https://www.zhihu.com/api/v4";
const PAGE_LIMIT: u32 = 20;

pub async fn run_sync(settings: &AppSettings) -> Result<u32> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let z_c0 = credential_store::get_credential(credential_store::KEY_ZHIHU_Z_C0)
        .unwrap_or(None)
        .unwrap_or_default();

    if z_c0.is_empty() {
        bail!("Zhihu credentials not configured");
    }

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let api_client = ApiClient::new(settings.server_url.clone(), api_key);

    let cookie = format!("z_c0={}", z_c0);
    let mut default_headers = reqwest::header::HeaderMap::new();
    let cookie_val = reqwest::header::HeaderValue::try_from(cookie.as_str())
        .context("Invalid Zhihu cookie format (non-ASCII characters in credentials)")?;
    default_headers.insert("Cookie", cookie_val);
    default_headers.insert(
        "User-Agent",
        reqwest::header::HeaderValue::from_static(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        ),
    );
    default_headers.insert(
        "x-udid",
        // Fixed placeholder udid — required by some Zhihu API endpoints
        reqwest::header::HeaderValue::from_static("AEDn6sBGMBWPTuZ2dERVRBJHMPgn2Q4"),
    );
    default_headers.insert(
        "Referer",
        reqwest::header::HeaderValue::from_static("https://www.zhihu.com"),
    );
    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .default_headers(default_headers)
        .build()?;

    // Three-step protocol
    let source_id = api_client
        .bookmark_setup("sync.zhihu")
        .await
        .context("zhihu bookmark setup failed")?;

    let last_sync_at = api_client.bookmark_status(&source_id).await.unwrap_or(None);
    let last_sync_ts: Option<i64> = last_sync_at
        .as_deref()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp());

    // Fetch favorite folders for "self"
    let favlists = fetch_favlists(&http).await?;
    if favlists.is_empty() {
        return Ok(0);
    }

    let mut total_synced = 0u32;

    for favlist in &favlists {
        let favlist_id = match favlist["id"].as_i64() {
            Some(id) => id,
            None => continue,
        };
        let favlist_title = favlist["title"].as_str().unwrap_or("").to_string();

        let items = fetch_favlist_items(&http, favlist_id, last_sync_ts).await?;
        if items.is_empty() {
            continue;
        }

        let bookmarks: Vec<Value> = items
            .iter()
            .filter_map(|item| {
                let content = &item["content"];
                let url = extract_zhihu_url(item, content)?;
                let title = content["title"].as_str().unwrap_or(&url).to_string();
                let added_at = item["created_time"]
                    .as_i64()
                    .and_then(|ts| chrono::DateTime::from_timestamp(ts, 0))
                    .map(|dt| dt.to_rfc3339());

                Some(json!({
                    "url": url,
                    "title": title,
                    "folder": favlist_title,
                    "added_at": added_at,
                }))
            })
            .collect();

        if bookmarks.is_empty() {
            continue;
        }

        const BATCH: usize = 50;
        for chunk in bookmarks.chunks(BATCH) {
            let payload = json!({
                "source_id": source_id,
                "bookmarks": chunk,
            });
            api_client
                .bookmark_sync(payload)
                .await
                .context("zhihu bookmark sync failed")?;
        }

        total_synced += bookmarks.len() as u32;
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }

    Ok(total_synced)
}

async fn fetch_favlists(http: &reqwest::Client) -> Result<Vec<Value>> {
    let resp = http
        .get(format!("{}/people/self/favlists", ZHIHU_API))
        .query(&[("include", "id,title,item_count"), ("limit", "100")])
        .send()
        .await
        .context("Zhihu favlists request failed")?;

    if resp.status().as_u16() == 401 || resp.status().as_u16() == 403 {
        bail!("Zhihu auth expired ({})", resp.status());
    }
    if !resp.status().is_success() {
        bail!("Zhihu favlists error: {}", resp.status());
    }

    let data: Value = resp.json().await?;
    Ok(data["data"].as_array().cloned().unwrap_or_default())
}

async fn fetch_favlist_items(
    http: &reqwest::Client,
    favlist_id: i64,
    since_ts: Option<i64>,
) -> Result<Vec<Value>> {
    let mut all_items: Vec<Value> = Vec::new();
    let mut offset = 0u32;

    loop {
        let resp = http
            .get(format!("{}/favlists/{}/items", ZHIHU_API, favlist_id))
            .query(&[
                ("limit", PAGE_LIMIT.to_string().as_str()),
                ("offset", &offset.to_string()),
            ])
            .send()
            .await
            .context("Zhihu favlist items request failed")?;

        if !resp.status().is_success() {
            break;
        }

        let data: Value = resp.json().await?;
        let items = data["data"].as_array().cloned().unwrap_or_default();
        if items.is_empty() {
            break;
        }

        let mut reached_old = false;
        for item in &items {
            let item_ts = item["created_time"].as_i64();
            match (item_ts, since_ts) {
                (Some(ts), Some(since)) if ts <= since => {
                    reached_old = true;
                }
                _ => {
                    all_items.push(item.clone());
                }
            }
        }

        let is_end = data["paging"]["is_end"].as_bool().unwrap_or(true);
        offset += items.len() as u32;

        if reached_old || is_end {
            break;
        }

        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }

    Ok(all_items)
}

/// Extract canonical URL from a Zhihu favorite item.
/// item["type"] can be "answer", "article", "zvideo", "pin", etc.
fn extract_zhihu_url(item: &Value, content: &Value) -> Option<String> {
    let item_type = item["type"].as_str().unwrap_or("");

    // Some items embed a direct url
    if let Some(url) = content["url"].as_str().filter(|s| !s.is_empty()) {
        return Some(url.to_string());
    }

    match item_type {
        "answer" => {
            let question_id = content["question"]["id"].as_i64()?;
            let answer_id = content["id"].as_i64()?;
            Some(format!(
                "https://www.zhihu.com/question/{}/answer/{}",
                question_id, answer_id
            ))
        }
        "article" => {
            let id = content["id"].as_i64()?;
            Some(format!("https://zhuanlan.zhihu.com/p/{}", id))
        }
        "zvideo" => {
            let id = content["id"].as_i64()?;
            Some(format!("https://www.zhihu.com/zvideo/{}", id))
        }
        _ => {
            // Fallback: try to build from id
            let id = content["id"].as_i64()?;
            Some(format!("https://www.zhihu.com/question/{}", id))
        }
    }
}
