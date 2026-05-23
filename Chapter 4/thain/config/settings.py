import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from a local .env file if present.
load_dotenv(override=False)


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


@dataclass(frozen=True)
class AzureAISearchConfig:
    """Configuration for Azure AI Search semantic recall."""

    endpoint: str
    index_name: str
    api_key: str | None
    embedding_endpoint: str
    embedding_deployment: str
    embedding_api_key: str | None
    embedding_api_version: str = "2024-02-15-preview"
    mode: str = "semantic"
    default_top_k: int = 3
    customer_id: str = "thain-demo"

    @classmethod
    def from_env(cls) -> "AzureAISearchConfig | None":
        endpoint = os.getenv("AZURE_SEARCH_ENDPOINT", "").strip()
        index_name = os.getenv("AZURE_SEARCH_INDEX_NAME", "").strip()
        embedding_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip()
        embedding_endpoint = os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT", "").strip()

        if not endpoint or not index_name or not embedding_deployment or not embedding_endpoint:
            return None

        api_key = os.getenv("AZURE_SEARCH_API_KEY", "").strip() or None
        embedding_api_key = os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY", "").strip() or None
        api_version = os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "").strip() or "2024-02-15-preview"
        mode = (os.getenv("AZURE_SEARCH_MODE", "semantic").strip() or "semantic").lower()
        default_top_k_raw = os.getenv("AZURE_SEARCH_TOP_K", "").strip()
        customer_id = os.getenv("THAIN_CUSTOMER_ID", "").strip() or "thain-demo"

        default_top_k = 3
        if default_top_k_raw:
            try:
                default_top_k = max(int(default_top_k_raw), 1)
            except ValueError:
                default_top_k = 3

        return cls(
            endpoint=endpoint,
            index_name=index_name,
            api_key=api_key,
            embedding_endpoint=embedding_endpoint,
            embedding_deployment=embedding_deployment,
            embedding_api_key=embedding_api_key,
            embedding_api_version=api_version,
            mode=mode,
            default_top_k=default_top_k,
            customer_id=customer_id,
        )


def load_search_config() -> AzureAISearchConfig | None:
    """Helper to load Azure AI Search configuration if available."""

    return AzureAISearchConfig.from_env()
