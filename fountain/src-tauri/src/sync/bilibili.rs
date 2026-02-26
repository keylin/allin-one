/// Bilibili favorites sync — ported from scripts/bilibili-sync.py
/// Uses SESSDATA + bili_jct + buvid3 cookies stored in Keychain.
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const BILI_API: &str = "https://api.bilibili.com";
const BATCH_SIZE: usize = 20;
const MAX_PAGES: u32 = 500;

pub async fn run_sync(settings: &AppSettings) -> Result<u32> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let sessdata = credential_store::get_credential(credential_store::KEY_BILIBILI_SESSDATA)
        .unwrap_or(None)
        .unwrap_or_default();
    let bili_jct = credential_store::get_credential(credential_store::KEY_BILIBILI_BILI_JCT)
        .unwrap_or(None)
        .unwrap_or_default();
    let buvid3 = credential_store::get_credential(credential_store::KEY_BILIBILI_BUVID3)
        .unwrap_or(None)
        .unwrap_or_default();

    if sessdata.is_empty() {
        bail!("Bilibili credentials not configured");
    }

    let cookie = format!(
        "SESSDATA={}; bili_jct={}; buvid3={}",
        sessdata, bili_jct, buvid3
    );
    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let api_client = ApiClient::new(settings.server_url.clone(), api_key);

    let mut default_headers = reqwest::header::HeaderMap::new();
    let cookie_val = reqwest::header::HeaderValue::try_from(cookie.as_str())
        .context("Invalid Bilibili cookie format (non-ASCII characters in credentials)")?;
    default_headers.insert("Cookie", cookie_val);
    default_headers.insert(
        "User-Agent",
        reqwest::header::HeaderValue::from_static(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        ),
    );
    default_headers.insert(
        "Referer",
        reqwest::header::HeaderValue::from_static("https://www.bilibili.com"),
    );
    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .default_headers(default_headers)
        .build()?;

    // Get user info to verify auth + get uid
    let nav_resp = http
        .get(format!("{}/x/web-interface/nav", BILI_API))
        .send()
        .await
        .context("Bilibili nav request failed")?;

    let nav: Value = nav_resp.json().await?;
    if nav["data"]["isLogin"].as_bool() != Some(true) {
        bail!("Bilibili auth expired — not logged in");
    }
    let uid = nav["data"]["mid"].as_i64().unwrap_or(0);
    let _uid_str = uid.to_string();

    // Three-step protocol
    let source_id = api_client
        .video_setup("sync.bilibili")
        .await
        .context("video setup failed")?;

    let last_sync_at = api_client.video_status(&source_id).await.unwrap_or(None);
    let last_sync_ts: Option<i64> = last_sync_at
        .as_deref()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.timestamp());

    // Fetch all favorite folders
    let fav_folders = fetch_favorite_folders(&http, uid).await?;
    let mut total_synced = 0u32;

    for folder in &fav_folders {
        let folder_id = folder["id"].as_i64().unwrap_or(0);
        if folder_id == 0 {
            continue; // skip malformed folder entries
        }
        let folder_title = folder["title"].as_str().unwrap_or("").to_string();

        let videos = fetch_folder_videos(&http, folder_id, last_sync_ts).await?;
        if videos.is_empty() {
            continue;
        }

        for chunk in videos.chunks(BATCH_SIZE) {
            let video_list: Vec<Value> = chunk
                .iter()
                .map(|v| {
                    let bvid = v["bvid"].as_str().unwrap_or("").to_string();
                    let duration = v["duration"].as_i64().unwrap_or(0);
                    let pub_ts = v["pubtime"].as_i64().unwrap_or(0);
                    let published_at = if pub_ts > 0 {
                        chrono::DateTime::from_timestamp(pub_ts, 0)
                            .map(|dt| dt.to_rfc3339())
                            .unwrap_or_default()
                    } else {
                        String::new()
                    };

                    json!({
                        "bvid": bvid,
                        "title": v["title"].as_str().unwrap_or(""),
                        "description": v["intro"].as_str().unwrap_or(""),
                        "cover_url": v["cover"].as_str().unwrap_or(""),
                        "duration": duration,
                        "published_at": published_at,
                        "upper_name": v["upper"]["name"].as_str().unwrap_or(""),
                        "upper_mid": v["upper"]["mid"].as_i64().unwrap_or(0),
                        "view_count": v["cnt_info"]["play"].as_i64().unwrap_or(0),
                        "folder_title": folder_title,
                    })
                })
                .collect();

            let payload = json!({
                "source_id": source_id,
                "videos": video_list,
            });

            api_client
                .video_sync(payload)
                .await
                .context("video sync failed")?;
            total_synced += chunk.len() as u32;
        }

        // Rate limit between folders
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }

    Ok(total_synced)
}

async fn fetch_favorite_folders(http: &reqwest::Client, uid: i64) -> Result<Vec<Value>> {
    let resp = http
        .get(format!("{}/x/v3/fav/folder/created/list-all", BILI_API))
        .query(&[("up_mid", uid.to_string().as_str()), ("type", "2")])
        .send()
        .await?;

    let data: Value = resp.json().await?;
    if data["code"].as_i64() != Some(0) {
        bail!(
            "Bilibili folders error: {}",
            data["message"].as_str().unwrap_or("unknown")
        );
    }

    Ok(data["data"]["list"].as_array().cloned().unwrap_or_default())
}

async fn fetch_folder_videos(http: &reqwest::Client, folder_id: i64, since_ts: Option<i64>) -> Result<Vec<Value>> {
    let mut all_videos = Vec::new();
    let mut page = 1u32;
    let page_size = 20u32;

    loop {
        let resp = http
            .get(format!("{}/x/v3/fav/resource/list", BILI_API))
            .query(&[
                ("media_id", folder_id.to_string().as_str()),
                ("pn", page.to_string().as_str()),
                ("ps", page_size.to_string().as_str()),
                ("keyword", ""),
                ("order", "mtime"),
                ("type", "0"),
                ("tid", "0"),
                ("platform", "web"),
            ])
            .send()
            .await?;

        let data: Value = resp.json().await?;
        if data["code"].as_i64() != Some(0) {
            break;
        }

        let medias = data["data"]["medias"].as_array().cloned().unwrap_or_default();
        if medias.is_empty() {
            break;
        }

        // Filter out deleted/unavailable videos (attr != 0 means unavailable)
        // Also filter by fav_time for incremental sync
        let valid: Vec<Value> = medias
            .into_iter()
            .filter(|v| {
                if v["attr"].as_i64().unwrap_or(0) != 0 {
                    return false; // unavailable
                }
                if let Some(since) = since_ts {
                    v["fav_time"].as_i64().map(|t| t > since).unwrap_or(true)
                } else {
                    true
                }
            })
            .collect();

        all_videos.extend(valid);

        let has_more = data["data"]["has_more"].as_bool().unwrap_or(false);
        if !has_more {
            break;
        }

        page += 1;
        if page > MAX_PAGES {
            log::warn!("Reached max pages ({MAX_PAGES}) for folder {folder_id}, stopping early");
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    }

    Ok(all_videos)
}
