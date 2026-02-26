/// Douban (豆瓣) sync — books and movies collected as "done".
/// Uses dbcl2 + bid cookies stored in Keychain.
/// Books → /api/ebook/sync (sync.douban_books)
/// Movies → /api/video/sync (sync.douban_movies, with rating/comment)
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const DOUBAN_API: &str = "https://www.douban.com";
const PAGE_SIZE: u32 = 30;

/// Returns (books_synced, movies_synced)
pub async fn run_sync(settings: &AppSettings) -> Result<(u32, u32)> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let dbcl2 = credential_store::get_credential(credential_store::KEY_DOUBAN_DBCL2)
        .unwrap_or(None)
        .unwrap_or_default();
    let bid = credential_store::get_credential(credential_store::KEY_DOUBAN_BID)
        .unwrap_or(None)
        .unwrap_or_default();

    if dbcl2.is_empty() {
        bail!("Douban credentials not configured");
    }

    // Extract UID from dbcl2 (format: "uid:hash" — value may or may not have surrounding quotes)
    let uid = dbcl2
        .trim_matches('"')
        .split(':')
        .next()
        .unwrap_or("")
        .to_string();
    if uid.is_empty() {
        bail!("Failed to extract UID from Douban dbcl2 cookie");
    }

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let api_client = ApiClient::new(settings.server_url.clone(), api_key);

    // Build the cookie header — preserve raw dbcl2 value (including quotes if any)
    let cookie = if bid.is_empty() {
        format!("dbcl2={}",  dbcl2)
    } else {
        format!("dbcl2={}; bid={}", dbcl2, bid)
    };

    let mut default_headers = reqwest::header::HeaderMap::new();
    let cookie_val = reqwest::header::HeaderValue::try_from(cookie.as_str())
        .context("Invalid Douban cookie format (non-ASCII characters in credentials)")?;
    default_headers.insert("Cookie", cookie_val);
    default_headers.insert(
        "User-Agent",
        reqwest::header::HeaderValue::from_static(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        ),
    );
    default_headers.insert(
        "Referer",
        reqwest::header::HeaderValue::from_static("https://www.douban.com"),
    );
    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .default_headers(default_headers)
        .build()?;

    let books_synced = sync_books(&http, &api_client, &uid).await?;
    let movies_synced = sync_movies(&http, &api_client, &uid).await?;

    Ok((books_synced, movies_synced))
}

async fn sync_books(http: &reqwest::Client, api_client: &ApiClient, uid: &str) -> Result<u32> {
    let source_id = api_client
        .ebook_setup("sync.douban_books")
        .await
        .context("douban books setup failed")?;

    let last_sync_at = api_client.ebook_status(&source_id).await.unwrap_or(None);
    let last_sync_ts: Option<i64> = last_sync_at
        .as_deref()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp());

    let items = fetch_douban_items(http, uid, "book", last_sync_ts).await?;
    if items.is_empty() {
        return Ok(0);
    }

    let ebooks: Vec<Value> = items
        .iter()
        .map(|item| {
            let subject = &item["subject"];
            let id = extract_subject_id(subject);

            // author is an array of strings
            let authors = subject["author"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                })
                .unwrap_or_default();

            let rating = extract_rating(item);
            let comment = item["comment"].as_str().filter(|s| !s.is_empty()).map(|s| s.to_string());

            json!({
                "external_id": id,
                "title": subject["title"].as_str().unwrap_or(""),
                "author": authors,
                "reading_progress": 1.0,
                "source_id": source_id,
                "annotations": [],
                "rating": rating,
                "comment": comment,
            })
        })
        .collect();

    const BATCH: usize = 20;
    for chunk in ebooks.chunks(BATCH) {
        let payload = json!({
            "source_id": source_id,
            "ebooks": chunk,
        });
        api_client
            .ebook_sync(payload)
            .await
            .context("douban books sync failed")?;
    }

    Ok(items.len() as u32)
}

async fn sync_movies(http: &reqwest::Client, api_client: &ApiClient, uid: &str) -> Result<u32> {
    let source_id = api_client
        .video_setup("sync.douban_movies")
        .await
        .context("douban movies setup failed")?;

    let last_sync_at = api_client.video_status(&source_id).await.unwrap_or(None);
    let last_sync_ts: Option<i64> = last_sync_at
        .as_deref()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp());

    let items = fetch_douban_items(http, uid, "movie", last_sync_ts).await?;
    if items.is_empty() {
        return Ok(0);
    }

    let videos: Vec<Value> = items
        .iter()
        .map(|item| {
            let subject = &item["subject"];
            let id = extract_subject_id(subject);

            // directors is an array of objects with "name" field
            let directors = subject["directors"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v["name"].as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                })
                .unwrap_or_default();

            let rating = extract_rating(item);
            let comment = item["comment"].as_str().filter(|s| !s.is_empty()).map(|s| s.to_string());
            let url = format!("https://movie.douban.com/subject/{}/", id);

            json!({
                "bvid": id,
                "title": subject["title"].as_str().unwrap_or(""),
                "author": directors,
                "url": url,
                "rating": rating,
                "comment": comment,
            })
        })
        .collect();

    const BATCH: usize = 20;
    for chunk in videos.chunks(BATCH) {
        let payload = json!({
            "source_id": source_id,
            "videos": chunk,
        });
        api_client
            .video_sync(payload)
            .await
            .context("douban movies sync failed")?;
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }

    Ok(items.len() as u32)
}

/// Fetch all "done" items of given type from Douban, stopping at items older than since_ts.
/// Items are sorted by create_time desc (sort=time).
async fn fetch_douban_items(
    http: &reqwest::Client,
    uid: &str,
    item_type: &str,
    since_ts: Option<i64>,
) -> Result<Vec<Value>> {
    let mut all_items: Vec<Value> = Vec::new();
    let mut start = 0u32;

    loop {
        let resp = http
            .get(format!("{}/j/people/{}/collect", DOUBAN_API, uid))
            .query(&[
                ("type", item_type),
                ("status", "done"),
                ("start", &start.to_string()),
                ("count", &PAGE_SIZE.to_string()),
                ("sort", "time"),
            ])
            .send()
            .await
            .context("Douban API request failed")?;

        if resp.status().as_u16() == 401 || resp.status().as_u16() == 403 {
            bail!("Douban auth expired ({})", resp.status());
        }
        if !resp.status().is_success() {
            bail!("Douban API error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        let items = data["items"].as_array().cloned().unwrap_or_default();
        if items.is_empty() {
            break;
        }

        let total = data["total"].as_i64().unwrap_or(0) as u32;
        let mut reached_old = false;

        for item in &items {
            let item_ts = parse_douban_create_time(item);
            match (item_ts, since_ts) {
                (Some(ts), Some(since)) if ts <= since => {
                    reached_old = true;
                    // Skip items that are at or before the last sync
                }
                _ => {
                    all_items.push(item.clone());
                }
            }
        }

        start += items.len() as u32;

        // Stop if we hit old items (sorted desc) or reached end
        if reached_old || start >= total || items.len() < PAGE_SIZE as usize {
            break;
        }

        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }

    Ok(all_items)
}

fn extract_subject_id(subject: &Value) -> String {
    // id can be a string or integer in the JSON
    if let Some(s) = subject["id"].as_str() {
        return s.to_string();
    }
    subject["id"].as_i64().unwrap_or(0).to_string()
}

fn extract_rating(item: &Value) -> Option<f64> {
    // rating can be {"value": 9.0} or {"value": "9.0"} or null
    item["rating"]["value"]
        .as_f64()
        .or_else(|| {
            item["rating"]["value"]
                .as_str()
                .and_then(|s| s.parse().ok())
        })
}

fn parse_douban_create_time(item: &Value) -> Option<i64> {
    let s = item["create_time"].as_str()?;
    // Format: "2024-01-15 20:30:00"
    chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S")
        .ok()
        .map(|dt| dt.and_utc().timestamp())
}
