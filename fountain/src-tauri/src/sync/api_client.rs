/// Client for the Allin-One backend — implements the three-step sync protocol:
///   1. POST /api/{ebook|video}/sync/setup  → source_id
///   2. GET  /api/{ebook|video}/sync/status → last_sync_at
///   3. POST /api/{ebook|video}/sync        → upsert data
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone)]
pub struct ApiClient {
    pub base_url: String,
    pub api_key: String,
    client: reqwest::Client,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct EbookSyncSetupRequest {
    pub platform: String,
    pub platform_user_id: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct VideoSyncSetupRequest {
    pub platform: String,
    pub platform_user_id: String,
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
            headers.insert(
                "X-API-Key",
                self.api_key.parse().expect("Invalid API key header"),
            );
        }
        headers
    }

    pub async fn ebook_setup(&self, platform: &str, user_id: &str) -> Result<i64> {
        let url = format!("{}/api/ebook/sync/setup", self.base_url);
        let body = EbookSyncSetupRequest {
            platform: platform.to_string(),
            platform_user_id: user_id.to_string(),
        };

        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .json(&body)
            .send()
            .await
            .context("ebook setup request failed")?;

        if !resp.status().is_success() {
            bail!("ebook setup error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        data["source_id"]
            .as_i64()
            .context("Missing source_id in setup response")
    }

    pub async fn ebook_status(&self, source_id: i64) -> Result<Option<String>> {
        let url = format!("{}/api/ebook/sync/status?source_id={}", self.base_url, source_id);
        let resp = self
            .client
            .get(&url)
            .headers(self.auth_headers())
            .send()
            .await
            .context("ebook status request failed")?;

        if !resp.status().is_success() {
            bail!("ebook status error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        Ok(data["last_sync_at"].as_str().map(|s| s.to_string()))
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

    pub async fn video_setup(&self, platform: &str, user_id: &str) -> Result<i64> {
        let url = format!("{}/api/video/sync/setup", self.base_url);
        let body = VideoSyncSetupRequest {
            platform: platform.to_string(),
            platform_user_id: user_id.to_string(),
        };

        let resp = self
            .client
            .post(&url)
            .headers(self.auth_headers())
            .json(&body)
            .send()
            .await
            .context("video setup request failed")?;

        if !resp.status().is_success() {
            bail!("video setup error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        data["source_id"]
            .as_i64()
            .context("Missing source_id in setup response")
    }

    pub async fn video_status(&self, source_id: i64) -> Result<Option<String>> {
        let url = format!("{}/api/video/sync/status?source_id={}", self.base_url, source_id);
        let resp = self
            .client
            .get(&url)
            .headers(self.auth_headers())
            .send()
            .await
            .context("video status request failed")?;

        if !resp.status().is_success() {
            bail!("video status error: {}", resp.status());
        }

        let data: Value = resp.json().await?;
        Ok(data["last_sync_at"].as_str().map(|s| s.to_string()))
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
}
