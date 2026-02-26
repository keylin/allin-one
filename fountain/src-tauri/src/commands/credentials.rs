use crate::credential_store::{self, *};
use serde::{Deserialize, Serialize};
use tauri::command;

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
