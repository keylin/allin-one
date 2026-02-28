/// Kindle sync — parses My Clippings.txt and pushes highlights to Allin-One backend.
///
/// Clippings format (one entry):
///   {Book Title (Author Name)}
///   - Your Highlight on Location 234-236 | Added on Monday, January 1, 2024 12:00:00
///
///   {highlighted text}
///   ==========
///
/// Notes and bookmarks are skipped; only highlights (with text) are pushed.
/// Kindle device must be connected (or the file manually copied).
use anyhow::{bail, Context, Result};
use chrono::NaiveDateTime;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const SEPARATOR: &str = "==========";
const BATCH_SIZE: usize = 50;

#[derive(Debug)]
struct Clipping {
    book_title: String,
    author: Option<String>,
    location: Option<String>,
    added_at: Option<String>,
    text: String,
}

/// Run Kindle sync.
/// Returns the number of books synced (books that had at least one new highlight).
pub async fn run_sync(settings: &AppSettings) -> Result<u32> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let clippings_path = find_clippings_file(settings)?;

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let client = ApiClient::new(settings.server_url.clone(), api_key);

    let source_id = client
        .ebook_setup("sync.kindle")
        .await
        .context("ebook setup failed for Kindle")?;

    let last_sync_at = client.ebook_status(&source_id).await?;
    let last_sync_ts = last_sync_at
        .as_deref()
        .and_then(|s| parse_iso_to_timestamp(s));

    let raw = std::fs::read_to_string(&clippings_path)
        .with_context(|| format!("Failed to read {:?}", clippings_path))?;

    let clippings = parse_clippings(&raw);
    if clippings.is_empty() {
        return Ok(0);
    }

    // Group by book
    let mut books_map: HashMap<String, Vec<&Clipping>> = HashMap::new();
    for clip in &clippings {
        books_map.entry(clip.book_title.clone()).or_default().push(clip);
    }

    // Filter: only books that have highlights newer than last_sync_ts
    let books_to_sync: Vec<(&String, &Vec<&Clipping>)> = books_map
        .iter()
        .filter(|(_, clips)| {
            if last_sync_ts.is_none() {
                return true; // first run — sync everything
            }
            let threshold = last_sync_ts.unwrap();
            clips.iter().any(|c| {
                c.added_at
                    .as_deref()
                    .and_then(|s| parse_iso_to_timestamp(s))
                    .map(|ts| ts > threshold)
                    .unwrap_or(false)
            })
        })
        .collect();

    if books_to_sync.is_empty() {
        return Ok(0);
    }

    let mut total_books_synced = 0u32;
    let all_books: Vec<(&String, &Vec<&Clipping>)> = books_to_sync;

    for chunk in all_books.chunks(BATCH_SIZE) {
        let ebooks: Vec<Value> = chunk
            .iter()
            .map(|(title, clips)| {
                let author = clips
                    .first()
                    .and_then(|c| c.author.clone())
                    .unwrap_or_default();

                let annotations: Vec<Value> = clips
                    .iter()
                    .filter(|c| !c.text.is_empty())
                    .map(|c| {
                        // Derive a stable ID from book+location
                        let raw_id = format!("{}:{}", title, c.location.as_deref().unwrap_or(""));
                        let id = stable_hash_hex(&raw_id);
                        json!({
                            "id": id,
                            "selected_text": c.text,
                            "note": null,
                            "color": "yellow",
                            "type": "highlight",
                            "chapter": null,
                            "location": c.location,
                            "created_at": c.added_at,
                            "is_deleted": false,
                        })
                    })
                    .collect();

                // Stable external_id from book title
                let external_id = stable_hash_hex(title.as_str());

                json!({
                    "external_id": external_id,
                    "title": title,
                    "author": author,
                    "reading_progress": 0.0,
                    "annotations": annotations,
                })
            })
            .collect();

        let payload = json!({
            "source_id": source_id,
            "books": ebooks,
        });

        client
            .ebook_sync(payload)
            .await
            .context("Kindle ebook sync batch failed")?;

        total_books_synced += chunk.len() as u32;
    }

    Ok(total_books_synced)
}

/// Find the My Clippings.txt file.
/// Checks custom path (from settings), then common Kindle mount points.
fn find_clippings_file(settings: &AppSettings) -> Result<PathBuf> {
    if let Some(custom) = &settings.kindle_clippings_path {
        let p = PathBuf::from(custom);
        if p.exists() {
            return Ok(p);
        }
        bail!("Kindle clippings file not found at configured path: {:?}", p);
    }

    // Auto-detect: Kindle appears as a volume under /Volumes on macOS
    #[cfg(target_os = "macos")]
    {
        if let Ok(entries) = std::fs::read_dir("/Volumes") {
            for entry in entries.flatten() {
                let candidate = entry.path().join("documents/My Clippings.txt");
                if candidate.exists() {
                    return Ok(candidate);
                }
            }
        }
    }

    bail!("Kindle not found. Connect your Kindle device or set the clippings file path in Settings.");
}

/// Parse My Clippings.txt content into a list of Clipping records.
fn parse_clippings(content: &str) -> Vec<Clipping> {
    let mut results = Vec::new();

    // Split on the "==========" separator
    for entry in content.split(SEPARATOR) {
        let entry = entry.trim();
        if entry.is_empty() {
            continue;
        }

        let mut lines = entry.lines();

        // Line 1: "Book Title (Author Name)"
        let Some(title_line) = lines.next() else {
            continue;
        };
        let title_line = title_line.trim().trim_start_matches('\u{feff}'); // strip BOM

        let (book_title, author) = parse_title_author(title_line);
        if book_title.is_empty() {
            continue;
        }

        // Line 2: "- Your Highlight on Location 123-456 | Added on ..."
        // Could also be "Your Note", "Your Bookmark", etc.
        let Some(meta_line) = lines.next() else {
            continue;
        };
        let meta_line = meta_line.trim();

        // Skip notes and bookmarks (no meaningful text to sync as highlights)
        let meta_lower = meta_line.to_lowercase();
        if meta_lower.contains("your note") || meta_lower.contains("your bookmark") {
            continue;
        }

        let (location, added_at) = parse_meta_line(meta_line);

        // Line 3: blank
        lines.next();

        // Remaining lines: the clipped text
        let text: String = lines
            .map(|l| l.trim())
            .filter(|l| !l.is_empty())
            .collect::<Vec<_>>()
            .join(" ");

        if text.is_empty() {
            continue;
        }

        results.push(Clipping {
            book_title,
            author,
            location,
            added_at,
            text,
        });
    }

    results
}

fn parse_title_author(line: &str) -> (String, Option<String>) {
    // Format: "Title (Author Name)" or just "Title"
    if let Some(paren_start) = line.rfind('(') {
        if line.ends_with(')') {
            let title = line[..paren_start].trim().to_string();
            let author = line[paren_start + 1..line.len() - 1].trim().to_string();
            if !title.is_empty() {
                return (title, if author.is_empty() { None } else { Some(author) });
            }
        }
    }
    (line.trim().to_string(), None)
}

fn parse_meta_line(line: &str) -> (Option<String>, Option<String>) {
    // "- Your Highlight on Location 234-236 | Added on Monday, January 1, 2024 12:00:00"
    let mut location = None;
    let mut added_at = None;

    // Extract location
    if let Some(loc_start) = line.to_lowercase().find("location ") {
        let after = &line[loc_start + "location ".len()..];
        let loc_end = after
            .find(|c: char| !c.is_numeric() && c != '-')
            .unwrap_or(after.len());
        let loc_str = after[..loc_end].trim().to_string();
        if !loc_str.is_empty() {
            location = Some(format!("Location {}", loc_str));
        }
    }

    // Extract "Added on ..."
    if let Some(added_start) = line.find("Added on ") {
        let date_str = line[added_start + "Added on ".len()..].trim();
        // Parse: "Monday, January 1, 2024 12:00:00"
        added_at = parse_kindle_date(date_str);
    }

    (location, added_at)
}

fn parse_kindle_date(date_str: &str) -> Option<String> {
    // Remove day-of-week prefix: "Monday, January 1, 2024 12:00:00" → "January 1, 2024 12:00:00"
    let stripped = if let Some(comma_pos) = date_str.find(", ") {
        // Check if first token is a weekday name
        let first = &date_str[..comma_pos];
        let weekdays = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
        if weekdays.contains(&first) {
            &date_str[comma_pos + 2..]
        } else {
            date_str
        }
    } else {
        date_str
    };

    // Try "January 1, 2024 12:00:00"
    if let Ok(dt) = NaiveDateTime::parse_from_str(stripped, "%B %e, %Y %H:%M:%S") {
        return Some(dt.format("%Y-%m-%dT%H:%M:%SZ").to_string());
    }

    None
}

/// Stable hash for deriving deterministic IDs from strings.
/// Uses SHA-256 (truncated to 16 hex chars) for cross-version stability.
fn stable_hash_hex(input: &str) -> String {
    use sha2::{Sha256, Digest};
    let hash = Sha256::digest(input.as_bytes());
    // First 8 bytes (16 hex chars) — sufficient for uniqueness
    hex_encode(&hash[..8])
}

fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

fn parse_iso_to_timestamp(s: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(s)
        .ok()
        .map(|dt| dt.timestamp())
}
