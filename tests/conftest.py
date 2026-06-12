import os

# Force DATABASE_URL to an in-memory SQLite database before any test imports shared.database
# to ensure that all tests interact only with the in-memory database, protecting the actual PostgreSQL database from being cleared.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
