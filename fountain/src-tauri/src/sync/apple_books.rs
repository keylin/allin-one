/// Apple Books sync — reads local SQLite databases and pushes to Allin-One backend.
///
/// Database locations (macOS):
///   ~/Library/Containers/com.apple.iBooksX/Data/Documents/
///     BKLibrary/BKLibrary-1-091020131601.sqlite       — book metadata
///     AEAnnotation/AEAnnotation_v10.sqlite             — annotations/highlights
///
/// Core Data timestamps: seconds since 2001-01-01 (reference date).
/// Unix epoch offset: 978307200 seconds.
use anyhow::{bail, Context, Result};
use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::config::AppSettings;
use crate::credential_store;
use crate::sync::api_client::ApiClient;

const COREDATA_EPOCH_OFFSET: i64 = 978307200;
const BATCH_SIZE: usize = 50;

/// Persisted per-book state used to detect changes between syncs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BookManifestEntry {
    pub annotation_count: usize,
    pub reading_progress: f64,
}

#[derive(Debug)]
struct Book {
    asset_id: String,
    title: String,
    author: String,
    genre: Option<String>,
    reading_progress: f64,
    cover_url: Option<String>,
}

#[derive(Debug)]
struct Annotation {
    id: String,
    asset_id: String,
    selected_text: Option<String>,
    note: Option<String>,
    color_style: u8,
    annotation_type: u8,
    chapter: Option<String>,
    created_at: Option<String>,
    location: Option<String>,
}

/// Run Apple Books sync.
///
/// `manifest` — per-book state from the previous sync (empty on first run).
///
/// Returns `(books_pushed, updated_manifest)`. If nothing changed, `books_pushed` is 0
/// and `updated_manifest` equals the input manifest.
pub async fn run_sync(
    settings: &AppSettings,
    manifest: &HashMap<String, BookManifestEntry>,
) -> Result<(u32, HashMap<String, BookManifestEntry>)> {
    if settings.server_url.is_empty() {
        bail!("Server URL not configured");
    }

    let api_key = credential_store::get_credential(credential_store::KEY_API_KEY)
        .unwrap_or(None)
        .unwrap_or_default();
    let client = ApiClient::new(settings.server_url.clone(), api_key);

    let db_base = find_apple_books_db(settings)?;
    let library_db = find_library_db(&db_base)?;
    let annotation_db = find_annotation_db(&db_base).unwrap_or_else(|_| {
        db_base.join("AEAnnotation/AEAnnotation_v10312011.sqlite")
    });

    // Read books from library DB
    let books = read_books(&library_db).context("Failed to read Apple Books library")?;
    if books.is_empty() {
        return Ok((0, manifest.clone()));
    }

    // Read all annotations
    let annotations = if annotation_db.exists() {
        read_annotations(&annotation_db).context("Failed to read Apple Books annotations")?
    } else {
        vec![]
    };

    // Build annotation lookup by asset_id
    let mut annots_by_asset: HashMap<String, Vec<&Annotation>> = HashMap::new();
    for a in &annotations {
        annots_by_asset.entry(a.asset_id.clone()).or_default().push(a);
    }

    // Three-step protocol: setup → source_id
    let source_id = client
        .ebook_setup("apple_books", "local")
        .await
        .context("ebook setup failed")?;

    // Filter to only books whose annotation count or reading progress changed
    let changed_books: Vec<&Book> = books
        .iter()
        .filter(|book| {
            let annot_count = annots_by_asset
                .get(&book.asset_id)
                .map_or(0, |a| a.len());
            match manifest.get(&book.asset_id) {
                None => true, // new book — always sync
                Some(entry) => {
                    entry.annotation_count != annot_count
                        || (entry.reading_progress - book.reading_progress).abs() > 0.005
                }
            }
        })
        .collect();

    if changed_books.is_empty() {
        return Ok((0, manifest.clone()));
    }

    // Push changed books in batches; include ALL their annotations (server upserts)
    let mut updated_manifest = manifest.clone();
    let mut total_synced = 0u32;

    for chunk in changed_books.chunks(BATCH_SIZE) {
        let ebooks: Vec<Value> = chunk
            .iter()
            .map(|book| {
                let book_annots: Vec<Value> = annots_by_asset
                    .get(&book.asset_id)
                    .map(|annots| annots.iter().map(|a| annotation_to_json(a)).collect())
                    .unwrap_or_default();

                json!({
                    "external_id": book.asset_id,
                    "title": book.title,
                    "author": book.author,
                    "genre": book.genre,
                    "reading_progress": book.reading_progress,
                    "cover_url": book.cover_url,
                    "source_id": source_id,
                    "annotations": book_annots,
                })
            })
            .collect();

        let payload = json!({
            "source_id": source_id,
            "ebooks": ebooks,
        });

        client
            .ebook_sync(payload)
            .await
            .context("ebook sync batch failed")?;

        // Update manifest for successfully pushed books
        for book in chunk {
            let annot_count = annots_by_asset
                .get(&book.asset_id)
                .map_or(0, |a| a.len());
            updated_manifest.insert(
                book.asset_id.clone(),
                BookManifestEntry {
                    annotation_count: annot_count,
                    reading_progress: book.reading_progress,
                },
            );
        }
        total_synced += chunk.len() as u32;
    }

    Ok((total_synced, updated_manifest))
}

fn find_apple_books_db(settings: &AppSettings) -> Result<PathBuf> {
    // Use custom path if configured
    if let Some(custom_path) = &settings.apple_books_db_path {
        let p = PathBuf::from(custom_path);
        if p.exists() {
            return Ok(p);
        }
    }

    #[cfg(target_os = "macos")]
    {
        let home = std::env::var("HOME").context("HOME not set")?;
        let base = PathBuf::from(&home)
            .join("Library/Containers/com.apple.iBooksX/Data/Documents");
        if base.exists() {
            return Ok(base);
        }

        // Fallback for older macOS
        let base2 =
            PathBuf::from(home).join("Library/Application Support/iBooks");
        if base2.exists() {
            return Ok(base2);
        }

        bail!("Apple Books database not found. Please verify iBooks/Books app is installed.");
    }

    #[cfg(not(target_os = "macos"))]
    bail!("Apple Books is only available on macOS");
}

fn find_library_db(base: &Path) -> Result<PathBuf> {
    let dir = base.join("BKLibrary");
    if !dir.exists() {
        bail!(
            "BKLibrary directory not found at {:?}. Apple Books may not have been opened yet.",
            dir
        );
    }

    // The filename includes a date suffix, find it dynamically
    for entry in std::fs::read_dir(&dir)? {
        let entry = entry?;
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if name_str.starts_with("BKLibrary") && name_str.ends_with(".sqlite") {
            return Ok(entry.path());
        }
    }

    bail!("BKLibrary SQLite file not found in {:?}", dir);
}

fn find_annotation_db(base: &Path) -> Result<PathBuf> {
    let dir = base.join("AEAnnotation");
    if !dir.exists() {
        bail!("AEAnnotation directory not found");
    }

    for entry in std::fs::read_dir(&dir)? {
        let entry = entry?;
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if name_str.starts_with("AEAnnotation") && name_str.ends_with(".sqlite") {
            return Ok(entry.path());
        }
    }

    bail!("AEAnnotation SQLite file not found in {:?}", dir);
}

fn read_books(db_path: &Path) -> Result<Vec<Book>> {
    let conn = Connection::open_with_flags(
        db_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;

    let mut stmt = conn.prepare(
        r#"
        SELECT
            ZASSETID,
            ZTITLE,
            ZAUTHOR,
            ZGENRE,
            ZREADINGPROGRESS,
            ZCOVERURL
        FROM ZBKLIBRARYASSET
        WHERE ZTITLE IS NOT NULL
          AND ZASSETID IS NOT NULL
        ORDER BY ZLASTOPENDATE DESC
        "#,
    )?;

    let books = stmt.query_map([], |row| {
        Ok(Book {
            asset_id: row.get::<_, String>(0)?,
            title: row.get::<_, String>(1)?,
            author: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
            genre: row.get::<_, Option<String>>(3)?,
            reading_progress: row.get::<_, Option<f64>>(4)?.unwrap_or(0.0),
            cover_url: row.get::<_, Option<String>>(5)?,
        })
    })?
    .collect::<Result<Vec<_>, _>>()?;

    Ok(books)
}

fn read_annotations(db_path: &Path) -> Result<Vec<Annotation>> {
    let conn = Connection::open_with_flags(
        db_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;

    // Check if table exists
    let table_exists: bool = conn
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='ZAEANNOTATION'",
            [],
            |row| row.get::<_, i64>(0),
        )
        .map(|c| c > 0)
        .unwrap_or(false);

    if !table_exists {
        return Ok(vec![]);
    }

    let mut stmt = conn.prepare(
        r#"
        SELECT
            ZANNOTATIONUUID,
            ZANNOTATIONASSETID,
            ZANNOTATIONSELECTEDTEXT,
            ZANNOTATIONNOTE,
            ZANNOTATIONSTYLE,
            ZANNOTATIONTYPE,
            ZFUTUREPROOFING5,
            ZANNOTATIONCREATIONDATE,
            ZANNOTATIONLOCATION
        FROM ZAEANNOTATION
        WHERE ZANNOTATIONDELETED = 0
          OR ZANNOTATIONDELETED IS NULL
        ORDER BY ZANNOTATIONCREATIONDATE ASC
        "#,
    )?;

    let annots = stmt.query_map([], |row| {
        let created_ts: Option<f64> = row.get(7)?;
        let created_at = created_ts.map(|ts| {
            let unix_ts = ts as i64 + COREDATA_EPOCH_OFFSET;
            chrono::DateTime::from_timestamp(unix_ts, 0)
                .map(|dt| dt.to_rfc3339())
                .unwrap_or_default()
        });

        Ok(Annotation {
            id: row.get::<_, Option<String>>(0)?.unwrap_or_default(),
            asset_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
            selected_text: row.get(2)?,
            note: row.get(3)?,
            color_style: row.get::<_, Option<i64>>(4)?.unwrap_or(0) as u8,
            annotation_type: row.get::<_, Option<i64>>(5)?.unwrap_or(2) as u8,
            chapter: row.get(6)?,
            created_at,
            location: row.get(8)?,
        })
    })?
    .collect::<Result<Vec<_>, _>>()?;

    Ok(annots)
}

fn annotation_to_json(a: &Annotation) -> Value {
    let color = match a.color_style {
        0 => "yellow",
        1 => "green",
        2 => "blue",
        3 => "pink",
        4 => "purple",
        _ => "yellow",
    };

    let annot_type = match a.annotation_type {
        2 => "highlight",
        3 => "note",
        _ => "highlight",
    };

    json!({
        "id": a.id,
        "selected_text": a.selected_text,
        "note": a.note,
        "color": color,
        "type": annot_type,
        "chapter": a.chapter,
        "created_at": a.created_at,
        "location": a.location,
    })
}
