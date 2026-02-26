use anyhow::{Context, Result};

const SERVICE: &str = "com.allinone.fountain";

pub fn get_credential(key: &str) -> Result<Option<String>> {
    #[cfg(target_os = "macos")]
    {
        use security_framework::passwords::get_generic_password;
        match get_generic_password(SERVICE, key) {
            Ok(bytes) => Ok(Some(String::from_utf8(bytes)?)),
            Err(e) if e.code() == -25300 => Ok(None), // errSecItemNotFound
            Err(e) => Err(e).context("Keychain read error"),
        }
    }
    #[cfg(target_os = "windows")]
    {
        get_windows_credential(key)
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        // Fallback: store in a file (dev only)
        let path = cred_file_path(key);
        if path.exists() {
            Ok(Some(std::fs::read_to_string(path)?))
        } else {
            Ok(None)
        }
    }
}

pub fn set_credential(key: &str, value: &str) -> Result<()> {
    #[cfg(target_os = "macos")]
    {
        use security_framework::passwords::set_generic_password;
        set_generic_password(SERVICE, key, value.as_bytes())
            .context("Keychain write error")?;
        Ok(())
    }
    #[cfg(target_os = "windows")]
    {
        set_windows_credential(key, value)
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        let path = cred_file_path(key);
        std::fs::write(path, value)?;
        Ok(())
    }
}

pub fn delete_credential(key: &str) -> Result<()> {
    #[cfg(target_os = "macos")]
    {
        use security_framework::passwords::delete_generic_password;
        match delete_generic_password(SERVICE, key) {
            Ok(_) => Ok(()),
            Err(e) if e.code() == -25300 => Ok(()), // already gone
            Err(e) => Err(e).context("Keychain delete error"),
        }
    }
    #[cfg(target_os = "windows")]
    {
        delete_windows_credential(key)
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        let path = cred_file_path(key);
        if path.exists() {
            std::fs::remove_file(path)?;
        }
        Ok(())
    }
}

// Credential keys
pub const KEY_API_KEY: &str = "api_key";
pub const KEY_BILIBILI_SESSDATA: &str = "bilibili_sessdata";
pub const KEY_BILIBILI_BILI_JCT: &str = "bilibili_bili_jct";
pub const KEY_BILIBILI_BUVID3: &str = "bilibili_buvid3";
pub const KEY_WECHAT_READ_SKEY: &str = "wechat_read_skey";
pub const KEY_WECHAT_READ_VID: &str = "wechat_read_vid";
pub const KEY_DOUBAN_DBCL2: &str = "douban_dbcl2";
pub const KEY_DOUBAN_BID: &str = "douban_bid";
pub const KEY_DOUBAN_UID: &str = "douban_uid";
pub const KEY_ZHIHU_Z_C0: &str = "zhihu_z_c0";
pub const KEY_GITHUB_TOKEN: &str = "github_token";
pub const KEY_TWITTER_AUTH_TOKEN: &str = "twitter_auth_token";
pub const KEY_TWITTER_CT0: &str = "twitter_ct0";
pub const KEY_TWITTER_SCREEN_NAME: &str = "twitter_screen_name";
pub const KEY_TWITTER_USER_ID: &str = "twitter_user_id";

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn cred_file_path(key: &str) -> std::path::PathBuf {
    let mut p = std::env::temp_dir();
    p.push(format!("allinone_sync_{}.cred", key));
    p
}

#[cfg(target_os = "windows")]
fn get_windows_credential(key: &str) -> Result<Option<String>> {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Security::Credentials::{
        CredReadW, CredFree, CREDENTIALW, CRED_TYPE_GENERIC,
    };

    let target: Vec<u16> = OsStr::new(&format!("{}:{}", SERVICE, key))
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let mut cred_ptr: *mut CREDENTIALW = std::ptr::null_mut();
        let result = CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut cred_ptr);
        if result == 0 {
            let err = windows_sys::Win32::Foundation::GetLastError();
            if err == 1168 {
                // ERROR_NOT_FOUND
                return Ok(None);
            }
            return Err(anyhow::anyhow!("CredReadW failed: {}", err));
        }
        let cred = &*cred_ptr;
        let blob = std::slice::from_raw_parts(
            cred.CredentialBlob,
            cred.CredentialBlobSize as usize,
        );
        let value = String::from_utf8(blob.to_vec())?;
        CredFree(cred_ptr as *mut _);
        Ok(Some(value))
    }
}

#[cfg(target_os = "windows")]
fn set_windows_credential(key: &str, value: &str) -> Result<()> {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Security::Credentials::{CredWriteW, CREDENTIALW, CRED_TYPE_GENERIC};

    let target: Vec<u16> = OsStr::new(&format!("{}:{}", SERVICE, key))
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let user: Vec<u16> = OsStr::new("allinone")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let blob = value.as_bytes();

    unsafe {
        let cred = CREDENTIALW {
            Flags: 0,
            Type: CRED_TYPE_GENERIC,
            TargetName: target.as_ptr() as *mut _,
            Comment: std::ptr::null_mut(),
            LastWritten: windows_sys::Win32::Foundation::FILETIME {
                dwLowDateTime: 0,
                dwHighDateTime: 0,
            },
            CredentialBlobSize: blob.len() as u32,
            CredentialBlob: blob.as_ptr() as *mut _,
            Persist: 2, // CRED_PERSIST_LOCAL_MACHINE
            AttributeCount: 0,
            Attributes: std::ptr::null_mut(),
            TargetAlias: std::ptr::null_mut(),
            UserName: user.as_ptr() as *mut _,
        };
        let result = CredWriteW(&cred, 0);
        if result == 0 {
            return Err(anyhow::anyhow!(
                "CredWriteW failed: {}",
                windows_sys::Win32::Foundation::GetLastError()
            ));
        }
        Ok(())
    }
}

#[cfg(target_os = "windows")]
fn delete_windows_credential(key: &str) -> Result<()> {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC};

    let target: Vec<u16> = OsStr::new(&format!("{}:{}", SERVICE, key))
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let result = CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0);
        if result == 0 {
            let err = windows_sys::Win32::Foundation::GetLastError();
            if err != 1168 {
                return Err(anyhow::anyhow!("CredDeleteW failed: {}", err));
            }
        }
        Ok(())
    }
}
