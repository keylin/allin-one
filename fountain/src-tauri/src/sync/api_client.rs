/// Client for the Allin-One backend — implements the three-step sync protocol:
///   1. POST /api/{ebook|video}/sync/setup  → source_id (string UUID)
///   2. GET  /api/{ebook|video}/sync/status → last_sync_at
///   3. POST /api/{ebook|video}/sync        → upsert data
use anyhow::{bail, Context, Result};
use reqwest::header::HeaderValue;
use serde_json::Value;
use std::fmt;

// ─── SyncError ──────────────────────────────────────────────────────────────

#[derive(Debug)]
pub enum SyncError {
    AuthExpired(String),
    NetworkError(String),
    ServerError(String),
    RateLimited(String),
    DataError(String),
}

impl fmt::Display for SyncError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SyncError::AuthExpired(msg) => write!(f, "auth expired: {}", msg),
            SyncError::NetworkError(msg) => write!(f, "network error: {}", msg),
            SyncError::ServerError(msg) => write!(f, "server error: {}", msg),
            SyncError::RateLimited(msg) => write!(f, "rate limited: {}", msg),
            SyncError::DataError(msg) => write!(f, "data error: {}", msg),
        }
    }
}

impl std::error::Error for SyncError {}

impl SyncError {
    /// Classify a reqwest error into a SyncError category.
    pub fn from_reqwest(e: &reqwest::Error) -> Self {
        if e.is_timeout() {
            SyncError::NetworkError(format!("request timed out: {}", e))
        } else if e.is_connect() {
            SyncError::NetworkError(format!("connection failed: {}", e))
        } else {
            SyncError::NetworkError(format!("{}", e))
        }
    }

    /// Classify an HTTP response status into a SyncError.
    pub fn from_status(status: reqwest::StatusCode, body: &str) -> Self {
        match status.as_u16() {
            401 | 403 => SyncError::AuthExpired(format!("{}: {}", status, body)),
            429 => SyncError::RateLimited(format!("{}: {}", status, body)),
            500..=599 => SyncError::ServerError(format!("{}: {}", status, body)),
            _ => SyncError::DataError(format!("{}: {}", status, body)),
        }
    }

    /// Whether this error type should be retried.
    pub fn is_retryable(&self) -> bool {
        matches!(self, SyncError::NetworkError(_) | SyncError::ServerError(_))
    }

    /// User-friendly error message.
    pub fn user_message(&self) -> &str {
        match self {
            SyncError::AuthExpired(_) => "登录已过期，请重新认证",
            SyncError::NetworkError(_) => "网络连接失败，请检查网络",
            SyncError::ServerError(_) => "无法连接 Allin-One 服务器",
            SyncError::RateLimited(_) => "请求过于频繁，请稍后再试",
            SyncError::DataError(_) => "数据处理失败",
        }
    }
}

// ─── ApiClient ──────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct ApiClient {
    pub base_url: String,
    pub api_key: String,
    client: reqwest::Client,
}

impl ApiClient {
    pub fn new(base_url: String, api_key: String) -> Self {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build()
            .expect("Failed to build HTTP client");

        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            api_key,
            client,
        }
    }

    fn auth_headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        if !self.api_key.is_empty() {
            if let Ok(val) = HeaderValue::try_from(&self.api_key) {
                headers.insert("X-API-Key", val);
            }
        }
        headers
    }

    /// POST with retry: up to 3 attempts, exponential backoff 1s/3s/9s.
    /// Only retries on NetworkError or ServerError.
    async fn post_with_retry(&self, url: &str, payload: &Value) -> Result<Value> {
        let delays = [1, 3, 9];
        let max_attempts = 3;

        for attempt in 0..max_attempts {
            let result = self
                .client
                .post(url)
                .headers(self.auth_headers())
                .json(payload)
                .send()
                .await;

            match result {
                Ok(resp) => {
                    let status = resp.status();
                    if status.is_success() {
                        return Ok(resp.json().await?);
                    }
                    let body = resp.text().await.unwrap_or_default();
                    let sync_err = SyncError::from_status(status, &body);
                    if sync_err.is_retryable() && attempt < max_attempts - 1 {
                        log::warn!(
                            "Retryable error on attempt {}/{}: {} (retrying in {}s)",
                            attempt + 1, max_attempts, sync_err, delays[attempt]
                        );
                        tokio::time::sleep(std::time::Duration::from_secs(delays[attempt])).await;
                        continue;
                    }
                    return Err(sync_err.into());
                }
                Err(e) => {
                    let sync_err = SyncError::from_reqwest(&e);
                    if sync_err.is_retryable() && attempt < max_attempts - 1 {
                        log::warn!(
                            "Network error on attempt {}/{}: {} (retrying in {}s)",
                            attempt + 1, max_attempts, sync_err, delays[attempt]
                        );
                        tokio::time::sleep(std::time::Duration::from_secs(delays[attempt])).await;
                        continue;
                    }
                    return Err(sync_err.into());
                }
            }
        }

        unreachable!()
    }

    pub async fn ebook_setup(&self, source_type: &str) -> Result<String> {
        let url = format!("{}/api/ebook/sync/setup", self.base_url);
        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .query(&[("source_type", source_type)])
            .send()
            .await
            .context("ebook setup request failed")?;

        if !resp.status().is_success() {
            bail!("ebook setup error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        data["data"]["source_id"]
            .as_str()
            .map(|s| s.to_string())
            .context("Missing source_id in setup response")
    }

    pub async fn ebook_status(&self, source_id: &str) -> Result<Option<String>> {
        let url = format!("{}/api/ebook/sync/status", self.base_url);
        let resp = self
            .client
            .get(&url)
            .headers(self.auth_headers())
            .query(&[("source_id", source_id)])
            .send()
            .await
            .context("ebook status request failed")?;

        if !resp.status().is_success() {
            bail!("ebook status error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        Ok(data["data"]["last_sync_at"].as_str().map(|s| s.to_string()))
    }

    pub async fn ebook_sync(&self, payload: Value) -> Result<Value> {
        let url = format!("{}/api/ebook/sync", self.base_url);
        self.post_with_retry(&url, &payload).await
    }

    pub async fn video_setup(&self, source_type: &str) -> Result<String> {
        let url = format!("{}/api/video/sync/setup", self.base_url);
        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .query(&[("source_type", source_type)])
            .send()
            .await
            .context("video setup request failed")?;

        if !resp.status().is_success() {
            bail!("video setup error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        data["data"]["source_id"]
            .as_str()
            .map(|s| s.to_string())
            .context("Missing source_id in setup response")
    }

    pub async fn video_status(&self, source_id: &str) -> Result<Option<String>> {
        let url = format!("{}/api/video/sync/status", self.base_url);
        let resp = self
            .client
            .get(&url)
            .headers(self.auth_headers())
            .query(&[("source_id", source_id)])
            .send()
            .await
            .context("video status request failed")?;

        if !resp.status().is_success() {
            bail!("video status error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        Ok(data["data"]["last_sync_at"].as_str().map(|s| s.to_string()))
    }

    pub async fn video_sync(&self, payload: Value) -> Result<Value> {
        let url = format!("{}/api/video/sync", self.base_url);
        self.post_with_retry(&url, &payload).await
    }

    pub async fn bookmark_setup(&self, source_type: &str) -> Result<String> {
        let url = format!("{}/api/bookmark/sync/setup", self.base_url);
        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .query(&[("source_type", source_type)])
            .send()
            .await
            .context("bookmark setup request failed")?;

        if !resp.status().is_success() {
            bail!("bookmark setup error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        data["data"]["source_id"]
            .as_str()
            .map(|s| s.to_string())
            .context("Missing source_id in bookmark setup response")
    }

    pub async fn bookmark_status(&self, source_id: &str) -> Result<Option<String>> {
        let url = format!("{}/api/bookmark/sync/status", self.base_url);
        let resp = self
            .client
            .get(&url)
            .headers(self.auth_headers())
            .query(&[("source_id", source_id)])
            .send()
            .await
            .context("bookmark status request failed")?;

        if !resp.status().is_success() {
            bail!("bookmark status error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        Ok(data["data"]["last_sync_at"].as_str().map(|s| s.to_string()))
    }

    pub async fn bookmark_sync(&self, payload: Value) -> Result<Value> {
        let url = format!("{}/api/bookmark/sync", self.base_url);
        self.post_with_retry(&url, &payload).await
    }
}
