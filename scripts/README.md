# Scripts Directory

Centralized location for all project scripts and utilities.

## Directory Structure

```
scripts/
├── init/         # Initialization scripts (database setup, etc.)
│   └── init-databases.sql   # PostgreSQL database and user creation
├── migration/    # Data migration scripts
│   ├── migrate_sqlite_to_pg.py  # SQLite to PostgreSQL migration
│   ├── rehash_title_dedup.py    # 重算 ContentItem title_hash
│   └── sync-data.sh             # 本地到远程数据同步
├── verify/       # Validation and verification scripts
│   └── timezone/ # Time zone related verification scripts
├── utils/        # Reusable utility scripts
│   └── logs.sh                  # 远程服务器日志查看工具
├── apple-books-sync.py          # Apple Books 同步脚本
├── bilibili-sync.py             # B站视频同步脚本
├── wechat-read-sync.py          # 微信读书同步脚本
├── com.allinone.apple-books-sync.plist  # macOS LaunchAgent (定时触发 apple-books-sync)
└── README.md     # This file
```

## Organization Guidelines

### Initialization Scripts (`init/`)
Scripts for setting up fresh environments.

- **Purpose**: Database initialization, service setup
- **Lifecycle**: Long-term, version controlled
- **Example**: `init/init-databases.sql` - creates PostgreSQL users and databases

### Migration Scripts (`migration/`)
Scripts for data migration or schema changes.

- **Purpose**: One-time migrations or database transformations
- **Lifecycle**: Keep for historical reference
- **Example**: `migration/migrate_sqlite_to_pg.py` - migrates from SQLite to PostgreSQL

### Verification Scripts (`verify/`)
Temporary scripts for validating specific features or bug fixes.

- **Purpose**: One-time or regression testing
- **Lifecycle**: May be deleted after validation or kept for regression tests
- **Example**: `verify/timezone/verify_timezone.py` - validates timezone boundary calculations

### Utility Scripts (`utils/`)
Reusable helper scripts for development or maintenance.

- **Purpose**: Long-term useful tools
- **Example**: `utils/logs.sh` - remote server log viewer
- **Example**: `utils/check-doc-drift.sh` - Claude Code Stop hook，检测代码变更但无文档更新时提醒同步

### Sync Scripts (root level)
External data sync scripts that push data to the backend via HTTP API.

- **Purpose**: Sync personal data from external platforms (Bilibili, WeChat Read, Apple Books)
- **Dependencies**: Only `httpx` (no backend environment needed)
- **Example**: `bilibili-sync.py` - syncs Bilibili favorites/history via `/api/video/sync`
- `com.allinone.apple-books-sync.plist` is a macOS LaunchAgent config for scheduling `apple-books-sync.py`

## Temporary Files

For purely temporary files (drafts, test data, one-off experiments), use the `.temp/` directory at project root:

```bash
.temp/  # Ignored by git, never committed
```

## Usage Examples

```bash
# Run timezone verification
python3 scripts/verify/timezone/verify_timezone.py

# Run database migration (from project root)
python3 scripts/migration/migrate_sqlite_to_pg.py

# Database initialization (automatically run by Docker)
# See docker-compose.remote.yml for usage

# Sync external data
python3 scripts/bilibili-sync.py --mode=incremental
python3 scripts/wechat-read-sync.py --mode=incremental
python3 scripts/apple-books-sync.py

# Add new verification script
mkdir -p scripts/verify/feature-name
touch scripts/verify/feature-name/verify_feature.py
```

## Best Practices

1. **Use descriptive names**: Script names should clearly indicate their purpose
2. **Add documentation**: Include comments or docstrings explaining what the script does
3. **Keep it organized**: Place scripts in appropriate subdirectories
4. **Version control**: Commit scripts that have long-term value, use `.temp/` for throwaway files
5. **Dependencies**: Document any special dependencies in the script header or this README
