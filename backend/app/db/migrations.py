from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def apply_safe_migrations(engine: Engine) -> None:
    """Small additive migrations for the MVP; never drops or rewrites user data."""
    inspector = inspect(engine)
    additions = {
        "memories": ("owner_id", "VARCHAR(80) NOT NULL DEFAULT 'shared'"),
        "tasks": ("owner_id", "VARCHAR(80) NOT NULL DEFAULT 'shared'"),
        "uploaded_files": ("owner_id", "VARCHAR(80) NOT NULL DEFAULT 'shared'"),
    }
    with engine.begin() as connection:
        for table, (column, definition) in additions.items():
            if table not in inspector.get_table_names():
                continue
            columns = {item["name"] for item in inspector.get_columns(table)}
            if column not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
