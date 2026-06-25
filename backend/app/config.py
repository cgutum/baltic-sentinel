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

    # Aiven MCP (hosted). When the token is set, the Evidence Librarian queries
    # Aiven through the official MCP server via the Anthropic API MCP connector.
    aiven_mcp_token: str = ""
    aiven_mcp_url: str = "https://mcp.aiven.live/mcp?read_only=true&allow_secrets=true"

    # When true, the backend uses cached demo assets instead of live calls.
    demo_mode: bool = True


settings = Settings()
