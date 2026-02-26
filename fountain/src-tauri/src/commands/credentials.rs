use crate::credential_store::{self, *};
use serde::{Deserialize, Serialize};
use tauri::{command, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

/// Initialization script injected into the WeChat Read WebView.
/// Polls document.cookie every 1.5 s; when both wr_skey and wr_vid are
/// visible (i.e., not HttpOnly), invokes the Rust command to capture them.
const WECHAT_INIT_SCRIPT: &str = r#"
(function () {
  'use strict';
  var _timer = setInterval(function () {
    try {
      var c = document.cookie || '';
      if (c.indexOf('wr_skey=') >= 0 && c.indexOf('wr_vid=') >= 0) {
        clearInterval(_timer);
        if (window.__TAURI__ && window.__TAURI__.core) {
          window.__TAURI__.core.invoke('capture_wechat_cookies', { cookies: c })
            .catch(function (e) { console.error('[Fountain] cookie capture failed:', e); });
        }
      }
    } catch (e) {}
  }, 1500);
})();
"#;

#[derive(Debug, Serialize, Deserialize)]
pub struct BilibiliQrResponse {
    pub qrcode_key: String,
    pub url: String,
    /// Base64-encoded QR code image (if generated client-side) or redirect URL
    pub qr_image_url: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct QrPollResponse {
    pub code: i32,
    pub message: String,
    pub is_success: bool,
    /// true when code == 86038 (QR code expired), frontend should stop polling
    pub is_expired: bool,
}

#[command]
pub fn get_credential(key: String) -> Result<Option<String>, String> {
    credential_store::get_credential(&key).map_err(|e| e.to_string())
}

#[command]
pub fn set_credential(key: String, value: String) -> Result<(), String> {
    credential_store::set_credential(&key, &value).map_err(|e| e.to_string())
}

#[command]
pub fn delete_credential(key: String) -> Result<(), String> {
    credential_store::delete_credential(&key).map_err(|e| e.to_string())
}

#[command]
pub async fn validate_bilibili_cookie() -> Result<bool, String> {
    let sessdata = credential_store::get_credential(KEY_BILIBILI_SESSDATA)
        .map_err(|e| e.to_string())?;
    let Some(sessdata) = sessdata else {
        return Ok(false);
    };
    if sessdata.is_empty() {
        return Ok(false);
    }

    let client = reqwest::Client::new();
    let resp = client
        .get("https://api.bilibili.com/x/web-interface/nav")
        .header("Cookie", format!("SESSDATA={}", sessdata))
        .header("User-Agent", "Mozilla/5.0")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    Ok(json["data"]["isLogin"].as_bool().unwrap_or(false))
}

#[command]
pub async fn validate_wechat_read_cookie() -> Result<bool, String> {
    let skey = credential_store::get_credential(KEY_WECHAT_READ_SKEY)
        .map_err(|e| e.to_string())?;
    let vid = credential_store::get_credential(KEY_WECHAT_READ_VID)
        .map_err(|e| e.to_string())?;

    let (Some(skey), Some(vid)) = (skey, vid) else {
        return Ok(false);
    };
    if skey.is_empty() || vid.is_empty() {
        return Ok(false);
    }

    let client = reqwest::Client::new();
    let cookie = format!("wr_skey={}; wr_vid={}", skey, vid);
    let resp = client
        .get("https://i.weread.qq.com/shelf/friendCommon")
        .header("Cookie", cookie)
        .header("User-Agent", "Mozilla/5.0")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    Ok(resp.status().is_success())
}

/// Step 1: Generate Bilibili QR code for login
#[command]
pub async fn start_bilibili_qr_login() -> Result<BilibiliQrResponse, String> {
    let client = reqwest::Client::new();
    let resp = client
        .get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
        .header("User-Agent", "Mozilla/5.0")
        .header("Referer", "https://www.bilibili.com")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;

    if json["code"].as_i64() != Some(0) {
        return Err(format!(
            "Bilibili API error: {}",
            json["message"].as_str().unwrap_or("unknown")
        ));
    }

    let qrcode_key = json["data"]["qrcode_key"]
        .as_str()
        .ok_or("Missing qrcode_key")?
        .to_string();
    let url = json["data"]["url"]
        .as_str()
        .ok_or("Missing url")?
        .to_string();

    // Generate QR code as base64 PNG using the URL
    let qr_image_url = generate_qr_data_url(&url)?;

    Ok(BilibiliQrResponse {
        qrcode_key,
        url,
        qr_image_url,
    })
}

/// Step 2: Poll QR code status; saves cookies to Keychain on success
#[command]
pub async fn poll_bilibili_qr_status(qrcode_key: String) -> Result<QrPollResponse, String> {
    let client = reqwest::Client::builder()
        .cookie_store(true)
        .build()
        .map_err(|e| e.to_string())?;

    let resp = client
        .get("https://passport.bilibili.com/x/passport-login/web/qrcode/poll")
        .query(&[("qrcode_key", &qrcode_key)])
        .header("User-Agent", "Mozilla/5.0")
        .header("Referer", "https://www.bilibili.com")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    // Extract Set-Cookie headers before consuming body
    let cookies: Vec<String> = resp
        .headers()
        .get_all("set-cookie")
        .iter()
        .filter_map(|v| v.to_str().ok().map(|s| s.to_string()))
        .collect();

    let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    let code = json["data"]["code"].as_i64().unwrap_or(-1) as i32;
    let message = json["data"]["message"]
        .as_str()
        .unwrap_or("")
        .to_string();

    let is_success = code == 0;
    let is_expired = code == 86038;
    if is_success {
        // Parse and store cookies
        save_bilibili_cookies(&cookies)?;
    }

    Ok(QrPollResponse {
        code,
        message,
        is_success,
        is_expired,
    })
}

/// Generate a QR code as a base64-encoded SVG data URL — no external service needed.
fn generate_qr_data_url(content: &str) -> Result<String, String> {
    use base64::Engine as _;
    use qrcodegen::{QrCode, QrCodeEcc};

    let qr = QrCode::encode_text(content, QrCodeEcc::Medium)
        .map_err(|e| format!("QR generation failed: {:?}", e))?;

    let svg = qr_to_svg(&qr);
    let encoded = base64::engine::general_purpose::STANDARD.encode(svg.as_bytes());
    Ok(format!("data:image/svg+xml;base64,{}", encoded))
}

fn qr_to_svg(qr: &qrcodegen::QrCode) -> String {
    let size = qr.size() as i32;
    let border: i32 = 4;
    let scale: i32 = 10;
    let total = (size + border * 2) * scale;

    let mut modules = String::new();
    for y in 0..size {
        for x in 0..size {
            if qr.get_module(x, y) {
                let rx = (x + border) * scale;
                let ry = (y + border) * scale;
                modules.push_str(&format!(
                    "<rect x=\"{rx}\" y=\"{ry}\" width=\"{scale}\" height=\"{scale}\"/>"
                ));
            }
        }
    }

    format!(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" \
         viewBox=\"0 0 {total} {total}\" width=\"{total}\" height=\"{total}\">\
         <rect width=\"{total}\" height=\"{total}\" fill=\"#fff\"/>\
         <g fill=\"#000\">{modules}</g>\
         </svg>"
    )
}

/// Open an in-app browser window pointing to WeChat Read for login.
/// An initialization script polls document.cookie; on success it calls
/// `capture_wechat_cookies` which saves the cookies and closes this window.
#[command]
pub async fn open_wechat_webview(app: tauri::AppHandle) -> Result<(), String> {
    // Close any pre-existing login window gracefully.
    if let Some(existing) = app.get_webview_window("wechat-login") {
        let _ = existing.close();
        tokio::time::sleep(tokio::time::Duration::from_millis(150)).await;
    }

    let url = "https://weread.qq.com"
        .parse::<url::Url>()
        .map_err(|e| e.to_string())?;

    WebviewWindowBuilder::new(&app, "wechat-login", WebviewUrl::External(url))
        .title("微信读书 — Login")
        .inner_size(960.0, 680.0)
        .center()
        .initialization_script(WECHAT_INIT_SCRIPT)
        .build()
        .map_err(|e| e.to_string())?;

    Ok(())
}

/// Called by the initialization script when wr_skey + wr_vid appear in
/// document.cookie (i.e., neither is HttpOnly).
/// Saves credentials to Keychain, closes the WebView, emits an event so the
/// Vue credential form can react.
#[command]
pub async fn capture_wechat_cookies(
    cookies: String,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let mut wr_skey: Option<String> = None;
    let mut wr_vid: Option<String> = None;

    for part in cookies.split(';') {
        let part = part.trim();
        if let Some((name, value)) = part.split_once('=') {
            match name.trim() {
                "wr_skey" => wr_skey = Some(value.trim().to_string()),
                "wr_vid" => wr_vid = Some(value.trim().to_string()),
                _ => {}
            }
        }
    }

    let (Some(skey), Some(vid)) = (wr_skey, wr_vid) else {
        // Partial cookies: both not yet visible, keep waiting (do nothing).
        return Ok(());
    };

    credential_store::set_credential(KEY_WECHAT_READ_SKEY, &skey).map_err(|e| e.to_string())?;
    credential_store::set_credential(KEY_WECHAT_READ_VID, &vid).map_err(|e| e.to_string())?;

    // Close the login window.
    if let Some(w) = app.get_webview_window("wechat-login") {
        let _ = w.close();
    }

    // Notify all windows (TrayPopover / CredentialForm listen for this).
    app.emit("wechat-cookies-captured", ())
        .map_err(|e| e.to_string())?;

    Ok(())
}

/// Close the WeChat login WebView without saving (user cancels).
#[command]
pub fn close_wechat_webview(app: tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("wechat-login") {
        let _ = w.close();
    }
}

// ─── Douban WebView login ──────────────────────────────────────────────────

/// Initialization script for the Douban login WebView.
/// Polls document.cookie every 1.5 s; when dbcl2 is visible (not HttpOnly),
/// invokes the Rust command to capture the cookies.
const DOUBAN_INIT_SCRIPT: &str = r#"
(function () {
  'use strict';
  var _timer = setInterval(function () {
    try {
      var c = document.cookie || '';
      if (c.indexOf('dbcl2=') >= 0) {
        clearInterval(_timer);
        if (window.__TAURI__ && window.__TAURI__.core) {
          window.__TAURI__.core.invoke('capture_douban_cookies', { cookies: c })
            .catch(function (e) { console.error('[Fountain] Douban cookie capture failed:', e); });
        }
      }
    } catch (e) {}
  }, 1500);
})();
"#;

#[command]
pub async fn open_douban_webview(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(existing) = app.get_webview_window("douban-login") {
        let _ = existing.close();
        tokio::time::sleep(tokio::time::Duration::from_millis(150)).await;
    }

    let url = "https://www.douban.com"
        .parse::<url::Url>()
        .map_err(|e| e.to_string())?;

    WebviewWindowBuilder::new(&app, "douban-login", WebviewUrl::External(url))
        .title("豆瓣 — Login")
        .inner_size(960.0, 680.0)
        .center()
        .initialization_script(DOUBAN_INIT_SCRIPT)
        .build()
        .map_err(|e| e.to_string())?;

    Ok(())
}

#[command]
pub async fn capture_douban_cookies(cookies: String, app: tauri::AppHandle) -> Result<(), String> {
    let mut dbcl2: Option<String> = None;
    let mut bid: Option<String> = None;

    for part in cookies.split(';') {
        let part = part.trim();
        if let Some((name, value)) = part.split_once('=') {
            match name.trim() {
                "dbcl2" => dbcl2 = Some(value.trim().to_string()),
                "bid" => bid = Some(value.trim().to_string()),
                _ => {}
            }
        }
    }

    let Some(dbcl2_val) = dbcl2 else {
        return Ok(()); // dbcl2 not yet visible, keep waiting
    };

    // Extract UID from dbcl2 (format: "uid:hash" — may have surrounding quotes)
    let uid = dbcl2_val
        .trim_matches('"')
        .split(':')
        .next()
        .unwrap_or("")
        .to_string();

    credential_store::set_credential(KEY_DOUBAN_DBCL2, &dbcl2_val).map_err(|e| e.to_string())?;
    if let Some(bid_val) = bid {
        credential_store::set_credential(KEY_DOUBAN_BID, &bid_val).map_err(|e| e.to_string())?;
    }
    if !uid.is_empty() {
        credential_store::set_credential(KEY_DOUBAN_UID, &uid).map_err(|e| e.to_string())?;
    }

    if let Some(w) = app.get_webview_window("douban-login") {
        let _ = w.close();
    }

    app.emit("douban-cookies-captured", ())
        .map_err(|e| e.to_string())?;

    Ok(())
}

#[command]
pub async fn validate_douban_cookie() -> Result<bool, String> {
    let dbcl2 = credential_store::get_credential(KEY_DOUBAN_DBCL2)
        .map_err(|e| e.to_string())?;
    let Some(dbcl2) = dbcl2 else {
        return Ok(false);
    };
    if dbcl2.is_empty() {
        return Ok(false);
    }

    let uid = dbcl2
        .trim_matches('"')
        .split(':')
        .next()
        .unwrap_or("")
        .to_string();
    if uid.is_empty() {
        return Ok(false);
    }

    let bid = credential_store::get_credential(KEY_DOUBAN_BID)
        .unwrap_or(None)
        .unwrap_or_default();
    let cookie = if bid.is_empty() {
        format!("dbcl2={}", dbcl2)
    } else {
        format!("dbcl2={}; bid={}", dbcl2, bid)
    };

    let client = reqwest::Client::new();
    let resp = client
        .get(format!(
            "https://www.douban.com/j/people/{}/collect?type=book&status=done&start=0&count=1",
            uid
        ))
        .header("Cookie", cookie)
        .header("User-Agent", "Mozilla/5.0")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    Ok(resp.status().is_success())
}

// ─── Zhihu WebView login ───────────────────────────────────────────────────

const ZHIHU_INIT_SCRIPT: &str = r#"
(function () {
  'use strict';
  var _timer = setInterval(function () {
    try {
      var c = document.cookie || '';
      if (c.indexOf('z_c0=') >= 0) {
        clearInterval(_timer);
        if (window.__TAURI__ && window.__TAURI__.core) {
          window.__TAURI__.core.invoke('capture_zhihu_cookies', { cookies: c })
            .catch(function (e) { console.error('[Fountain] Zhihu cookie capture failed:', e); });
        }
      }
    } catch (e) {}
  }, 1500);
})();
"#;

#[command]
pub async fn open_zhihu_webview(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(existing) = app.get_webview_window("zhihu-login") {
        let _ = existing.close();
        tokio::time::sleep(tokio::time::Duration::from_millis(150)).await;
    }

    let url = "https://www.zhihu.com"
        .parse::<url::Url>()
        .map_err(|e| e.to_string())?;

    WebviewWindowBuilder::new(&app, "zhihu-login", WebviewUrl::External(url))
        .title("知乎 — Login")
        .inner_size(960.0, 680.0)
        .center()
        .initialization_script(ZHIHU_INIT_SCRIPT)
        .build()
        .map_err(|e| e.to_string())?;

    Ok(())
}

#[command]
pub async fn capture_zhihu_cookies(cookies: String, app: tauri::AppHandle) -> Result<(), String> {
    let mut z_c0: Option<String> = None;

    for part in cookies.split(';') {
        let part = part.trim();
        if let Some((name, value)) = part.split_once('=') {
            if name.trim() == "z_c0" {
                z_c0 = Some(value.trim().to_string());
                break;
            }
        }
    }

    let Some(z_c0_val) = z_c0 else {
        return Ok(()); // z_c0 not yet visible
    };

    credential_store::set_credential(KEY_ZHIHU_Z_C0, &z_c0_val).map_err(|e| e.to_string())?;

    if let Some(w) = app.get_webview_window("zhihu-login") {
        let _ = w.close();
    }

    app.emit("zhihu-cookies-captured", ())
        .map_err(|e| e.to_string())?;

    Ok(())
}

#[command]
pub async fn validate_zhihu_cookie() -> Result<bool, String> {
    let z_c0 = credential_store::get_credential(KEY_ZHIHU_Z_C0)
        .map_err(|e| e.to_string())?;
    let Some(z_c0) = z_c0 else {
        return Ok(false);
    };
    if z_c0.is_empty() {
        return Ok(false);
    }

    let client = reqwest::Client::new();
    let resp = client
        .get("https://www.zhihu.com/api/v4/me")
        .header("Cookie", format!("z_c0={}", z_c0))
        .header("User-Agent", "Mozilla/5.0")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    Ok(resp.status().is_success())
}

// ─── GitHub Token ─────────────────────────────────────────────────────────

#[command]
pub async fn validate_github_token() -> Result<bool, String> {
    let token = credential_store::get_credential(KEY_GITHUB_TOKEN)
        .map_err(|e| e.to_string())?;
    let Some(token) = token else {
        return Ok(false);
    };
    if token.is_empty() {
        return Ok(false);
    }

    let client = reqwest::Client::new();
    let resp = client
        .get("https://api.github.com/user")
        .header("Authorization", format!("Bearer {}", token))
        .header("Accept", "application/vnd.github.v3+json")
        .header("User-Agent", "Fountain")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    Ok(resp.status().is_success())
}

// ─── Twitter/X WebView login ───────────────────────────────────────────────

/// Initialization script for the Twitter login WebView.
/// Polls document.cookie every 1.5 s; when ct0 is visible (not HttpOnly),
/// invokes the Rust command to capture it.
/// Note: auth_token IS HttpOnly and cannot be captured this way — user must
/// enter it manually from DevTools.
const TWITTER_INIT_SCRIPT: &str = r#"
(function () {
  'use strict';
  var _timer = setInterval(function () {
    try {
      var c = document.cookie || '';
      if (c.indexOf('ct0=') >= 0) {
        clearInterval(_timer);
        if (window.__TAURI__ && window.__TAURI__.core) {
          window.__TAURI__.core.invoke('capture_twitter_ct0', { cookies: c })
            .catch(function (e) { console.error('[Fountain] Twitter ct0 capture failed:', e); });
        }
      }
    } catch (e) {}
  }, 1500);
})();
"#;

#[command]
pub async fn open_twitter_webview(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(existing) = app.get_webview_window("twitter-login") {
        let _ = existing.close();
        tokio::time::sleep(tokio::time::Duration::from_millis(150)).await;
    }

    let url = "https://x.com"
        .parse::<url::Url>()
        .map_err(|e| e.to_string())?;

    WebviewWindowBuilder::new(&app, "twitter-login", WebviewUrl::External(url))
        .title("Twitter / X — Login")
        .inner_size(960.0, 680.0)
        .center()
        .initialization_script(TWITTER_INIT_SCRIPT)
        .build()
        .map_err(|e| e.to_string())?;

    Ok(())
}

/// Called by the initialization script when ct0 appears in document.cookie.
/// Stores ct0 in Keychain and emits an event so the Vue form can react.
/// auth_token is HttpOnly and must be entered manually by the user.
#[command]
pub async fn capture_twitter_ct0(
    cookies: String,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let mut ct0: Option<String> = None;

    for part in cookies.split(';') {
        let part = part.trim();
        if let Some((name, value)) = part.split_once('=') {
            if name.trim() == "ct0" {
                ct0 = Some(value.trim().to_string());
                break;
            }
        }
    }

    let Some(ct0_val) = ct0 else {
        return Ok(()); // ct0 not yet visible
    };

    credential_store::set_credential(KEY_TWITTER_CT0, &ct0_val).map_err(|e| e.to_string())?;

    // Keep the window open — user still needs to enter auth_token manually
    app.emit("twitter-ct0-captured", ())
        .map_err(|e| e.to_string())?;

    Ok(())
}

/// Save auth_token + ct0, then verify credentials and store screen_name/user_id.
#[command]
pub async fn save_twitter_cookies(
    auth_token: String,
    ct0: String,
    app: tauri::AppHandle,
) -> Result<(), String> {
    if auth_token.is_empty() || ct0.is_empty() {
        return Err("auth_token and ct0 are required".to_string());
    }

    credential_store::set_credential(KEY_TWITTER_AUTH_TOKEN, &auth_token)
        .map_err(|e| e.to_string())?;
    credential_store::set_credential(KEY_TWITTER_CT0, &ct0)
        .map_err(|e| e.to_string())?;

    // Verify credentials and fetch user info
    let client = reqwest::Client::new();
    let resp = client
        .get("https://api.twitter.com/1.1/account/verify_credentials.json")
        .query(&[("skip_status", "1")])
        .header(
            "authorization",
            format!("Bearer {}", TWITTER_BEARER),
        )
        .header("cookie", format!("auth_token={}; ct0={}", auth_token, ct0))
        .header("x-csrf-token", ct0.as_str())
        .header("User-Agent", "Mozilla/5.0")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if !resp.status().is_success() {
        return Err(format!("Twitter verify_credentials failed: {}", resp.status()));
    }

    let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;

    let screen_name = json["screen_name"]
        .as_str()
        .ok_or("verify_credentials: missing screen_name in response")?;
    let id_str = json["id_str"]
        .as_str()
        .ok_or("verify_credentials: missing id_str in response")?;
    credential_store::set_credential(KEY_TWITTER_SCREEN_NAME, screen_name)
        .map_err(|e| e.to_string())?;
    credential_store::set_credential(KEY_TWITTER_USER_ID, id_str)
        .map_err(|e| e.to_string())?;

    // Close login window if still open
    if let Some(w) = app.get_webview_window("twitter-login") {
        let _ = w.close();
    }

    app.emit("twitter-cookies-captured", ())
        .map_err(|e| e.to_string())?;

    Ok(())
}

#[command]
pub async fn validate_twitter_cookie() -> Result<bool, String> {
    let auth_token = credential_store::get_credential(KEY_TWITTER_AUTH_TOKEN)
        .map_err(|e| e.to_string())?;
    let ct0 = credential_store::get_credential(KEY_TWITTER_CT0)
        .map_err(|e| e.to_string())?;

    let (Some(auth_token), Some(ct0)) = (auth_token, ct0) else {
        return Ok(false);
    };
    if auth_token.is_empty() || ct0.is_empty() {
        return Ok(false);
    }

    let client = reqwest::Client::new();
    let resp = client
        .get("https://api.twitter.com/1.1/account/verify_credentials.json")
        .query(&[("skip_status", "1")])
        .header(
            "authorization",
            format!("Bearer {}", TWITTER_BEARER),
        )
        .header("cookie", format!("auth_token={}; ct0={}", auth_token, ct0))
        .header("x-csrf-token", ct0.as_str())
        .header("User-Agent", "Mozilla/5.0")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    Ok(resp.status().is_success())
}

fn save_bilibili_cookies(set_cookie_headers: &[String]) -> Result<(), String> {
    let mut sessdata = None;
    let mut bili_jct = None;
    let mut buvid3 = None;

    for cookie_str in set_cookie_headers {
        let name_value = cookie_str.split(';').next().unwrap_or("");
        let parts: Vec<&str> = name_value.splitn(2, '=').collect();
        if parts.len() == 2 {
            let name = parts[0].trim();
            let value = parts[1].trim();
            match name {
                "SESSDATA" => sessdata = Some(value.to_string()),
                "bili_jct" => bili_jct = Some(value.to_string()),
                "buvid3" => buvid3 = Some(value.to_string()),
                _ => {}
            }
        }
    }

    // All three cookies must be present before writing any — avoids partial Keychain state
    let (Some(sessdata), Some(bili_jct), Some(buvid3)) = (sessdata, bili_jct, buvid3) else {
        return Err(
            "Incomplete cookie set from QR login (missing SESSDATA, bili_jct, or buvid3)".into(),
        );
    };

    credential_store::set_credential(KEY_BILIBILI_SESSDATA, &sessdata)
        .map_err(|e| e.to_string())?;
    credential_store::set_credential(KEY_BILIBILI_BILI_JCT, &bili_jct)
        .map_err(|e| e.to_string())?;
    credential_store::set_credential(KEY_BILIBILI_BUVID3, &buvid3)
        .map_err(|e| e.to_string())?;

    Ok(())
}
