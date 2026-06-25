"""Central configuration.

Reads from environment / .env. Everything here is optional at H0 so the
backend boots even before Aiven is connected. Owners fill these in as their
parts come online.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Loads from a .env file at the repo root if present.
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic (Person B agents)
    anthropic_api_key: str = ""

    # ElevenLabs (Person B voice)
    elevenlabs_api_key: str = ""

    # Aiven Kafka
    aiven_kafka_bootstrap: str = ""
    aiven_kafka_username: str = ""
    aiven_kafka_password: str = ""
    aiven_kafka_ca: str = "backend/ca.pem"

    # Aiven Postgres
    aiven_postgres_url: str = ""

    # Aiven MCP (hosted). The agents reach the Aiven data layer through the official
    # MCP server via the Anthropic API MCP connector. WRITABLE: read_only removed so
    # agents can run SQL writes / provision infra (aiven_pg_write etc.); allow_secrets
    # lets the MCP fetch the service credentials it needs to connect to Postgres.
    aiven_mcp_token: str = ""
    aiven_mcp_url: str = "https://mcp.aiven.live/mcp?allow_secrets=true"

    # Aiven service coordinates the agents pass to the MCP Postgres tools
    # (aiven_pg_read / aiven_pg_write). Confirmed via the MCP write smoke test.
    aiven_project: str = "baltic-sentinel"
    aiven_pg_service: str = "baltic-pg"
    aiven_pg_database: str = "defaultdb"

    # When true, the backend uses cached demo assets instead of live calls.
    demo_mode: bool = True


settings = Settings()
