/// Client for the Allin-One backend — implements the three-step sync protocol:
///   1. POST /api/{ebook|video}/sync/setup  → source_id (string UUID)
///   2. GET  /api/{ebook|video}/sync/status → last_sync_at
///   3. POST /api/{ebook|video}/sync        → upsert data
use anyhow::{bail, Context, Result};
use reqwest::header::HeaderValue;
use serde_json::Value;

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
            // Use try_from to avoid panicking on malformed API keys from Keychain
            if let Ok(val) = HeaderValue::try_from(&self.api_key) {
                headers.insert("X-API-Key", val);
            }
        }
        headers
    }

    /// Setup sync source. `source_type` must be a valid sync.* SourceType value
    /// (e.g. "sync.apple_books", "sync.wechat_read", "sync.bilibili").
    /// Returns the source UUID string from the backend.
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
        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .json(&payload)
            .send()
            .await
            .context("ebook sync request failed")?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            bail!("ebook sync error {}: {}", status, body);
        }

        Ok(resp.json().await?)
    }

    /// Setup video sync source. `source_type` must be a valid sync.* SourceType value
    /// (e.g. "sync.bilibili"). Returns the source UUID string from the backend.
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
        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .json(&payload)
            .send()
            .await
            .context("video sync request failed")?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            bail!("video sync error {}: {}", status, body);
        }

        Ok(resp.json().await?)
    }

    /// Setup bookmark sync source. `source_type` must be "sync.safari_bookmarks"
    /// or "sync.chrome_bookmarks". Returns the source UUID string from the backend.
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
        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .json(&payload)
            .send()
            .await
            .context("bookmark sync request failed")?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            bail!("bookmark sync error {}: {}", status, body);
        }

        Ok(resp.json().await?)
    }
}
