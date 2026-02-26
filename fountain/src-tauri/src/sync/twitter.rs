/// Twitter/X sync.
/// Uses auth_token (HttpOnly, manually entered) + ct0 (captured from WebView).
/// Fetches user timeline via v1.1 API → pushes to /api/bookmark/sync.
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

/// Twitter web app's built-in Bearer token — embedded in x.com frontend JS,
/// used by many open-source tools for anonymous API access.
const TWITTER_BEARER: &str = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA";

pub async fn run_sync(settings: &AppSettings) -> Result<u32> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let auth_token = credential_store::get_credential(credential_store::KEY_TWITTER_AUTH_TOKEN)
        .unwrap_or(None)
        .unwrap_or_default();
    let ct0 = credential_store::get_credential(credential_store::KEY_TWITTER_CT0)
        .unwrap_or(None)
        .unwrap_or_default();
    let user_id = credential_store::get_credential(credential_store::KEY_TWITTER_USER_ID)
        .unwrap_or(None)
        .unwrap_or_default();

    if auth_token.is_empty() || ct0.is_empty() || user_id.is_empty() {
        bail!("Twitter credentials not configured");
    }

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let api_client = ApiClient::new(settings.server_url.clone(), api_key);

    let mut default_headers = reqwest::header::HeaderMap::new();
    let bearer_val = reqwest::header::HeaderValue::try_from(
        format!("Bearer {}", TWITTER_BEARER)
    ).context("Invalid Twitter bearer token")?;
    default_headers.insert("authorization", bearer_val);

    let cookie_val = reqwest::header::HeaderValue::try_from(
        format!("auth_token={}; ct0={}", auth_token, ct0)
    ).context("Invalid Twitter cookie format (non-ASCII characters in credentials)")?;
    default_headers.insert("cookie", cookie_val);

    let csrf_val = reqwest::header::HeaderValue::try_from(ct0.as_str())
        .context("Invalid ct0 format")?;
    default_headers.insert("x-csrf-token", csrf_val);

    default_headers.insert(
        "User-Agent",
        reqwest::header::HeaderValue::from_static(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        ),
    );

    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .default_headers(default_headers)
        .build()?;

    let source_id = api_client
        .bookmark_setup("sync.twitter")
        .await
        .context("twitter bookmark setup failed")?;

    let last_sync_at = api_client.bookmark_status(&source_id).await.unwrap_or(None);
    let last_sync_ts: Option<chrono::DateTime<chrono::Utc>> = last_sync_at
        .as_deref()
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.with_timezone(&chrono::Utc));

    let tweets = fetch_timeline(&http, &user_id, last_sync_ts).await?;
    if tweets.is_empty() {
        return Ok(0);
    }

    let bookmarks: Vec<Value> = tweets
        .iter()
        .filter_map(|tweet| {
            let id_str = tweet["id_str"].as_str()?;
            let screen_name = tweet["user"]["screen_name"].as_str().unwrap_or("twitter");
            let full_text = tweet["full_text"]
                .as_str()
                .or_else(|| tweet["text"].as_str())
                .unwrap_or("");
            let title = if full_text.len() > 200 {
                format!("{}…", &full_text[..200])
            } else {
                full_text.to_string()
            };
            let url = format!(
                "https://twitter.com/{}/status/{}",
                screen_name, id_str
            );
            let is_retweet = tweet["retweeted_status"].is_object()
                || full_text.starts_with("RT @");
            let folder = if is_retweet { "retweet" } else { "tweet" };

            let created_at_str = tweet["created_at"].as_str().unwrap_or("");
            let added_at = parse_twitter_date(created_at_str)
                .map(|dt| dt.to_rfc3339());

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
            .context("twitter bookmark sync failed")?;
    }

    Ok(count)
}

async fn fetch_timeline(
    http: &reqwest::Client,
    user_id: &str,
    since: Option<chrono::DateTime<chrono::Utc>>,
) -> Result<Vec<Value>> {
    let mut all_tweets: Vec<Value> = Vec::new();
    let mut max_id: Option<u128> = None;

    loop {
        let mut params = vec![
            ("user_id", user_id.to_string()),
            ("count", "200".to_string()),
            ("include_rts", "1".to_string()),
            ("tweet_mode", "extended".to_string()),
        ];
        if let Some(mid) = max_id {
            params.push(("max_id", mid.to_string()));
        }

        let resp = http
            .get("https://api.twitter.com/1.1/statuses/user_timeline.json")
            .query(&params)
            .send()
            .await
            .context("Twitter timeline request failed")?;

        if resp.status().as_u16() == 401 || resp.status().as_u16() == 403 {
            bail!("Twitter auth expired ({})", resp.status());
        }
        if !resp.status().is_success() {
            bail!("Twitter timeline error: {}", resp.status());
        }

        let tweets: Vec<Value> = resp
            .json()
            .await
            .context("Failed to parse Twitter timeline response")?;

        if tweets.is_empty() {
            break;
        }

        let mut reached_old = false;
        let mut min_numeric_id: Option<u128> = None;

        for tweet in &tweets {
            let created_at_str = tweet["created_at"].as_str().unwrap_or("");
            let tweet_dt = parse_twitter_date(created_at_str);

            if let (Some(dt), Some(since_ts)) = (tweet_dt, since) {
                if dt <= since_ts {
                    reached_old = true;
                    break;
                }
            }

            // Track minimum id for pagination
            if let Some(id_str) = tweet["id_str"].as_str() {
                if let Ok(id_num) = id_str.parse::<u128>() {
                    min_numeric_id = Some(match min_numeric_id {
                        Some(cur) if id_num < cur => id_num,
                        None => id_num,
                        Some(cur) => cur,
                    });
                }
            }

            all_tweets.push(tweet.clone());
        }

        if reached_old {
            break;
        }

        // Set max_id to min_id - 1 to avoid re-fetching the last tweet
        match min_numeric_id {
            Some(id) if id > 0 => max_id = Some(id - 1),
            _ => break,
        }

        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }

    Ok(all_tweets)
}

/// Parse Twitter's date format: "Mon Jan 01 00:00:00 +0000 2024"
fn parse_twitter_date(s: &str) -> Option<chrono::DateTime<chrono::Utc>> {
    chrono::DateTime::parse_from_str(s, "%a %b %d %H:%M:%S %z %Y")
        .ok()
        .map(|dt| dt.with_timezone(&chrono::Utc))
}
