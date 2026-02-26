/// GitHub Stars sync.
/// Uses a Personal Access Token stored in Keychain.
/// Fetches starred repositories → pushes to /api/bookmark/sync.
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const GITHUB_API: &str = "https://api.github.com";

pub async fn run_sync(settings: &AppSettings) -> Result<u32> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let token = credential_store::get_credential(credential_store::KEY_GITHUB_TOKEN)
        .unwrap_or(None)
        .unwrap_or_default();

    if token.is_empty() {
        bail!("GitHub token not configured");
    }

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let api_client = ApiClient::new(settings.server_url.clone(), api_key);

    let mut default_headers = reqwest::header::HeaderMap::new();
    let auth_val = reqwest::header::HeaderValue::try_from(format!("Bearer {}", token))
        .context("Invalid GitHub token format")?;
    default_headers.insert("Authorization", auth_val);
    default_headers.insert(
        "Accept",
        reqwest::header::HeaderValue::from_static("application/vnd.github.v3+json"),
    );
    default_headers.insert(
        "User-Agent",
        reqwest::header::HeaderValue::from_static("Fountain"),
    );
    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .default_headers(default_headers)
        .build()?;

    let source_id = api_client
        .bookmark_setup("sync.github_stars")
        .await
        .context("github_stars bookmark setup failed")?;

    let last_sync_at = api_client.bookmark_status(&source_id).await.unwrap_or(None);
    let last_sync_ts: Option<chrono::DateTime<chrono::Utc>> = last_sync_at
        .as_deref()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.with_timezone(&chrono::Utc));

    let stars = fetch_stars(&http, last_sync_ts).await?;
    if stars.is_empty() {
        return Ok(0);
    }

    let bookmarks: Vec<Value> = stars
        .iter()
        .filter_map(|item| {
            let url = item["html_url"].as_str()?.to_string();
            let title = item["full_name"].as_str().unwrap_or(&url).to_string();
            let folder = item["language"]
                .as_str()
                .filter(|s| !s.is_empty())
                .unwrap_or("Other")
                .to_string();
            let added_at = item["starred_at"]
                .as_str()
                .map(|s| s.to_string());

            Some(json!({
                "url": url,
                "title": title,
                "folder": folder,
                "added_at": added_at,
            }))
        })
        .collect();

    if bookmarks.is_empty() {
        return Ok(0);
    }

    let count = bookmarks.len() as u32;
    const BATCH: usize = 50;
    for chunk in bookmarks.chunks(BATCH) {
        let payload = json!({
            "source_id": source_id,
            "bookmarks": chunk,
        });
        api_client
            .bookmark_sync(payload)
            .await
            .context("github_stars bookmark sync failed")?;
    }

    Ok(count)
}

async fn fetch_stars(
    http: &reqwest::Client,
    since: Option<chrono::DateTime<chrono::Utc>>,
) -> Result<Vec<Value>> {
    let mut all_stars: Vec<Value> = Vec::new();
    let mut page = 1u32;

    loop {
        let resp = http
            .get(format!("{}/user/starred", GITHUB_API))
            .query(&[
                ("per_page", "100"),
                ("sort", "created"),
                ("direction", "desc"),
                ("page", &page.to_string()),
            ])
            // Request starred_at field via Accept header for the starring timestamp
            .header("Accept", "application/vnd.github.star+json")
            .send()
            .await
            .context("GitHub stars request failed")?;

        if resp.status().as_u16() == 401 {
            bail!("GitHub token invalid or expired (401)");
        }
        if !resp.status().is_success() {
            bail!("GitHub stars API error: {}", resp.status());
        }

        let items: Vec<Value> = resp.json().await.context("Failed to parse GitHub stars response")?;
        if items.is_empty() {
            break;
        }

        let mut reached_old = false;
        for item in &items {
            // With star+json Accept header, each item has { starred_at, repo: {...} }
            // Without it, each item IS the repo directly.
            let (repo, starred_at_str) = if item["repo"].is_object() {
                (
                    &item["repo"],
                    item["starred_at"].as_str().map(|s| s.to_string()),
                )
            } else {
                (item, None)
            };

            let starred_at: Option<chrono::DateTime<chrono::Utc>> = starred_at_str
                .as_deref()
                .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
                .map(|dt| dt.with_timezone(&chrono::Utc));

            if let (Some(ts), Some(since_ts)) = (starred_at, since) {
                if ts <= since_ts {
                    reached_old = true;
                    break;
                }
            }

            // Build a flat entry using repo fields plus starred_at.
            // If starred_at is missing (non-star+json response), omit the field
            // so the backend uses ingestion time — repo.created_at is the repo
            // creation date, not the star date, and must not be used as a proxy.
            let mut entry = repo.clone();
            if let Some(sa) = starred_at_str {
                entry["starred_at"] = Value::String(sa);
            }
            all_stars.push(entry);
        }

        if reached_old {
            break;
        }

        // Check Link header for next page
        page += 1;

        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    }

    Ok(all_stars)
}
