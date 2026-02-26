# Scripts Directory

Centralized location for all project scripts and utilities.

## Directory Structure

```
scripts/
├── init/         # Initialization scripts (database setup, etc.)
│   └── init-databases.sql # PostgreSQL database and user creation
├── migration/    # Data migration scripts
│   └── migrate_sqlite_to_pg.py # SQLite to PostgreSQL migration
├── verify/       # Validation and verification scripts
│   └── timezone/ # Time zone related verification scripts
├── utils/        # Reusable utility scripts (currently empty)
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
- **Example**: Data seeding, cleanup utilities, development helpers

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
