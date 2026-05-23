import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from a local .env file if present.
load_dotenv(override=True)


class MissingConfigError(RuntimeError):
    """Raised when required Azure configuration values are not provided."""


@dataclass(frozen=True)
class AzureAgentConfig:
    """Typed container for Azure OpenAI Agent settings."""

    endpoint: str
    model: str

    @classmethod
    def from_env(cls) -> "AzureAgentConfig":
        """Create configuration from environment variables."""
        endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
        model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()

        if not endpoint:
            raise MissingConfigError(
                "Missing Azure configuration value: endpoint. Set AZURE_AI_PROJECT_ENDPOINT environment variable."
            )

        if not model:
            raise MissingConfigError(
                "Missing model deployment name. Set AZURE_AI_MODEL_DEPLOYMENT_NAME in your .env file "
                "to match your deployed model (e.g., gpt-4o)."
            )
            
        return cls(endpoint=endpoint, model=model)


@dataclass(frozen=True)
class PersistentMemoryConfig:
    """Configuration for Cosmos DB-backed persistent memory."""

    endpoint: str
    database: str
    container: str
    ttl_days: int = 30
    key: str | None = None
    customer_id: str = "thain-demo"

    @property
    def ttl_seconds(self) -> int:
        return max(self.ttl_days, 0) * 24 * 60 * 60

    @classmethod
    def from_env(cls) -> "PersistentMemoryConfig | None":
        endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
        database = os.getenv("COSMOS_DATABASE", "").strip()
        container = os.getenv("COSMOS_CONTAINER", "").strip()

        if not endpoint or not database or not container:
            return None

        key = os.getenv("COSMOS_KEY", "").strip() or None
        ttl_days_raw = os.getenv("COSMOS_TTL_DAYS", "").strip()
        customer_id = os.getenv("THAIN_CUSTOMER_ID", "").strip() or "thain-demo"

        ttl_days = 30
        if ttl_days_raw:
            try:
                ttl_days = max(int(ttl_days_raw), 0)
            except ValueError:
                ttl_days = 30

        return cls(
            endpoint=endpoint,
            database=database,
            container=container,
            key=key,
            ttl_days=ttl_days,
            customer_id=customer_id,
        )


def load_config() -> AzureAgentConfig:
    """Helper to load Azure configuration from the environment."""

    return AzureAgentConfig.from_env()


def load_persistent_config() -> PersistentMemoryConfig | None:
    """Helper to load persistent memory configuration if available."""

    return PersistentMemoryConfig.from_env()
