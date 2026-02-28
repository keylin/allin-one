fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&[
                // settings
                "open_settings_window",
                "get_settings",
                "save_settings",
                "test_server_connection",
                // credentials — generic
                "get_credential",
                "set_credential",
                "delete_credential",
                // credentials — bilibili
                "validate_bilibili_cookie",
                "start_bilibili_qr_login",
                "poll_bilibili_qr_status",
                // credentials — wechat read
                "validate_wechat_read_cookie",
                "open_wechat_webview",
                "capture_wechat_cookies",
                "close_wechat_webview",
                // credentials — douban
                "open_douban_webview",
                "capture_douban_cookies",
                "validate_douban_cookie",
                // credentials — zhihu
                "open_zhihu_webview",
                "capture_zhihu_cookies",
                "validate_zhihu_cookie",
                // credentials — github
                "validate_github_token",
                // credentials — twitter
                "open_twitter_webview",
                "capture_twitter_ct0",
                "save_twitter_cookies",
                "validate_twitter_cookie",
                // sync
                "sync_now",
                "sync_platform",
                "get_sync_status",
            ]),
        ),
    )
    .unwrap();
}
