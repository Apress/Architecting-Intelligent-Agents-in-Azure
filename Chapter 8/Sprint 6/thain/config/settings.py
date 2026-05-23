import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from a local .env file if present.
load_dotenv(override=False)


class MissingConfigError(RuntimeError):
    """Raised when required Azure configuration values are not provided."""

_KEY_ENV_VARS = {
    "COSMOS_KEY",
    "AZURE_SEARCH_API_KEY",
    "AZURE_OPENAI_EMBEDDING_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_CONTENT_SAFETY_API_KEY",
    "APPROVALS_LOGIC_APP_URL",
    "APPROVALS_CALLBACK_SECRET",
}


def load_auth_mode() -> str:
    raw = os.getenv("THAIN_AUTH_MODE", "local").strip().lower()
    if raw in {"managed_identity", "managed-identity", "mi", "azure"}:
        return "managed_identity"
    return "local"


def load_safety_provider() -> str:
    raw = os.getenv("SAFETY_PROVIDER", "auto").strip().lower()
    if raw in {"azure", "local", "auto"}:
        return raw
    return "auto"


def _raw_env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _strip_key_if_managed_identity(value: str | None) -> str | None:
    if load_auth_mode() == "managed_identity":
        return None
    return value


def validate_cloud_config() -> None:
    """Fail fast when running in managed identity mode with unsafe config."""

    key_vars = [name for name in _KEY_ENV_VARS if os.getenv(name, "").strip()]
    if key_vars:
        raise MissingConfigError(
            f"Cloud mode disallows embedded secrets. Remove these env vars: {', '.join(sorted(key_vars))}."
        )

    required = {
        "AZURE_AI_PROJECT_ENDPOINT": os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip(),
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise MissingConfigError(
            f"Missing required cloud configuration values: {', '.join(sorted(missing))}."
        )

    safety_provider = load_safety_provider()
    if safety_provider in {"azure", "auto"}:
        safety_endpoint = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT", "").strip()
        if not safety_endpoint:
            raise MissingConfigError(
                "Missing Azure Content Safety endpoint. Set AZURE_CONTENT_SAFETY_ENDPOINT or switch SAFETY_PROVIDER=local."
            )

    search_mode = (os.getenv("AZURE_SEARCH_MODE", "semantic").strip() or "semantic").lower()
    if search_mode != "off":
        search_required = {
            "AZURE_SEARCH_ENDPOINT": os.getenv("AZURE_SEARCH_ENDPOINT", "").strip(),
            "AZURE_SEARCH_INDEX_NAME": os.getenv("AZURE_SEARCH_INDEX_NAME", "").strip(),
            "AZURE_OPENAI_EMBEDDING_ENDPOINT": os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT", "").strip(),
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip(),
        }
        missing_search = [name for name, value in search_required.items() if not value]
        if missing_search:
            raise MissingConfigError(
                f"Missing required Azure Search configuration values: {', '.join(sorted(missing_search))}."
            )

    if _raw_env_flag("ENABLE_DOCS", False):
        docs_required = {
            "AZURE_SEARCH_ENDPOINT": os.getenv("AZURE_SEARCH_ENDPOINT", "").strip(),
            "AZURE_SEARCH_DOCS_INDEX_NAME": os.getenv("AZURE_SEARCH_DOCS_INDEX_NAME", "").strip(),
            "AZURE_OPENAI_EMBEDDING_ENDPOINT": os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT", "").strip(),
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip(),
        }
        missing_docs = [name for name, value in docs_required.items() if not value]
        if missing_docs:
            raise MissingConfigError(
                "Missing required docs retrieval configuration values: "
                f"{', '.join(sorted(missing_docs))}."
            )

    if _raw_env_flag("ENABLE_WRITE_APPROVALS", False):
        approvals_required = {
            "COSMOS_ENDPOINT": os.getenv("COSMOS_ENDPOINT", "").strip(),
            "COSMOS_DATABASE": os.getenv("COSMOS_DATABASE", "").strip(),
            "APPROVALS_CONTAINER": os.getenv("APPROVALS_CONTAINER", "").strip(),
            "APPROVALS_GROUP": os.getenv("APPROVALS_GROUP", "").strip(),
            "APPROVALS_CALLBACK_URL": os.getenv("APPROVALS_CALLBACK_URL", "").strip(),
        }
        missing_approvals = [name for name, value in approvals_required.items() if not value]
        if missing_approvals:
            raise MissingConfigError(
                "Missing required approval configuration values: "
                f"{', '.join(sorted(missing_approvals))}."
            )

        if not (
            os.getenv("APPROVALS_LOGIC_APP_URL", "").strip()
            or os.getenv("KV_APPROVALS_LOGIC_APP_URL_NAME", "").strip()
        ):
            raise MissingConfigError(
                "Missing approval workflow URL. Set APPROVALS_LOGIC_APP_URL or KV_APPROVALS_LOGIC_APP_URL_NAME."
            )

        if not (
            os.getenv("APPROVALS_CALLBACK_SECRET", "").strip()
            or os.getenv("KV_APPROVALS_CALLBACK_SECRET_NAME", "").strip()
        ):
            raise MissingConfigError(
                "Missing approval callback secret. Set APPROVALS_CALLBACK_SECRET or KV_APPROVALS_CALLBACK_SECRET_NAME."
            )

        if (
            os.getenv("KV_APPROVALS_LOGIC_APP_URL_NAME", "").strip()
            or os.getenv("KV_APPROVALS_CALLBACK_SECRET_NAME", "").strip()
        ):
            key_vault_uri = os.getenv("KEY_VAULT_URI", "").strip()
            if not key_vault_uri:
                raise MissingConfigError(
                    "Missing KEY_VAULT_URI required for approval secrets."
                )

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
        key = _strip_key_if_managed_identity(key)
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
        mode = (os.getenv("AZURE_SEARCH_MODE", "semantic").strip() or "semantic").lower()

        if mode == "off":
            return None

        if not endpoint or not index_name or not embedding_deployment or not embedding_endpoint:
            return None

        api_key = os.getenv("AZURE_SEARCH_API_KEY", "").strip() or None
        api_key = _strip_key_if_managed_identity(api_key)
        embedding_api_key = os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY", "").strip() or None
        api_version = os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "").strip() or "2024-02-15-preview"
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


@dataclass(frozen=True)
class AzureAIDocsSearchConfig:
    """Configuration for Azure AI Search document retrieval."""

    endpoint: str
    index_name: str
    api_key: str | None
    embedding_endpoint: str
    embedding_deployment: str
    embedding_api_key: str | None
    embedding_api_version: str = "2024-02-15-preview"
    default_top_k: int = 3

    @classmethod
    def from_env(cls) -> "AzureAIDocsSearchConfig | None":
        endpoint = os.getenv("AZURE_SEARCH_ENDPOINT", "").strip()
        index_name = os.getenv("AZURE_SEARCH_DOCS_INDEX_NAME", "").strip()
        embedding_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip()
        embedding_endpoint = os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT", "").strip()

        if not endpoint or not index_name or not embedding_deployment or not embedding_endpoint:
            return None

        api_key = os.getenv("AZURE_SEARCH_API_KEY", "").strip() or None
        api_key = _strip_key_if_managed_identity(api_key)
        embedding_api_key = os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY", "").strip() or None
        api_version = os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "").strip() or "2024-02-15-preview"
        default_top_k_raw = os.getenv("AZURE_SEARCH_DOCS_TOP_K", "").strip()

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
            default_top_k=default_top_k,
        )


def load_docs_search_config() -> AzureAIDocsSearchConfig | None:
    """Helper to load Azure AI Search docs retrieval configuration if available."""

    return AzureAIDocsSearchConfig.from_env()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class ActionToolsConfig:
    """Configuration for optional action tools (tickets, notifications, docs)."""

    enable_tickets: bool = False
    enable_notifications: bool = False
    enable_docs: bool = False

    @classmethod
    def from_env(cls) -> "ActionToolsConfig":
        return cls(
            enable_tickets=_env_flag("ENABLE_TICKETS", False),
            enable_notifications=_env_flag("ENABLE_NOTIFICATIONS", False),
            enable_docs=_env_flag("ENABLE_DOCS", False),
        )


def load_action_tools_config() -> ActionToolsConfig:
    """Helper to load action tool configuration from the environment."""

    return ActionToolsConfig.from_env()


def load_write_approvals_enabled() -> bool:
    """Helper to load the write-approval toggle from the environment."""

    return _env_flag("ENABLE_WRITE_APPROVALS", False)


@dataclass(frozen=True)
class ApprovalStoreConfig:
    """Configuration for Cosmos DB-backed approval records."""

    endpoint: str
    database: str
    container: str
    ttl_days: int = 30
    key: str | None = None

    @property
    def ttl_seconds(self) -> int:
        return max(self.ttl_days, 0) * 24 * 60 * 60

    @classmethod
    def from_env(cls) -> "ApprovalStoreConfig | None":
        endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
        database = os.getenv("COSMOS_DATABASE", "").strip()
        container = os.getenv("APPROVALS_CONTAINER", "").strip()

        if not endpoint or not database or not container:
            return None

        key = os.getenv("COSMOS_KEY", "").strip() or None
        key = _strip_key_if_managed_identity(key)
        ttl_days_raw = os.getenv("APPROVALS_TTL_DAYS", "").strip()

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
        )


def load_approval_store_config() -> ApprovalStoreConfig | None:
    """Helper to load approval store configuration if available."""

    return ApprovalStoreConfig.from_env()


@dataclass(frozen=True)
class ApprovalWorkflowConfig:
    """Configuration for approval workflows and callbacks."""

    approvals_group: str
    callback_url: str
    logic_app_url: str | None
    logic_app_url_secret_name: str | None
    callback_secret: str | None
    callback_secret_name: str | None
    timeout_seconds: int = 90
    expires_seconds: int = 900
    poll_interval_seconds: int = 2
    max_poll_interval_seconds: int = 10

    @classmethod
    def from_env(cls) -> "ApprovalWorkflowConfig | None":
        approvals_group = os.getenv("APPROVALS_GROUP", "").strip()
        callback_url = os.getenv("APPROVALS_CALLBACK_URL", "").strip()
        logic_app_url = os.getenv("APPROVALS_LOGIC_APP_URL", "").strip() or None
        logic_app_url_name = os.getenv("KV_APPROVALS_LOGIC_APP_URL_NAME", "").strip() or None
        callback_secret = os.getenv("APPROVALS_CALLBACK_SECRET", "").strip() or None
        callback_secret_name = os.getenv("KV_APPROVALS_CALLBACK_SECRET_NAME", "").strip() or None

        if not approvals_group or not callback_url:
            return None

        timeout_raw = os.getenv("APPROVALS_TIMEOUT_SECONDS", "").strip()
        expires_raw = os.getenv("APPROVALS_EXPIRES_SECONDS", "").strip()
        poll_raw = os.getenv("APPROVALS_POLL_INTERVAL_SECONDS", "").strip()
        max_poll_raw = os.getenv("APPROVALS_MAX_POLL_INTERVAL_SECONDS", "").strip()

        timeout_seconds = 90
        expires_seconds = 900
        poll_interval_seconds = 2
        max_poll_interval_seconds = 10

        if timeout_raw:
            try:
                timeout_seconds = max(int(timeout_raw), 5)
            except ValueError:
                timeout_seconds = 90
        if expires_raw:
            try:
                expires_seconds = max(int(expires_raw), 60)
            except ValueError:
                expires_seconds = 900
        if poll_raw:
            try:
                poll_interval_seconds = max(int(poll_raw), 1)
            except ValueError:
                poll_interval_seconds = 2
        if max_poll_raw:
            try:
                max_poll_interval_seconds = max(int(max_poll_raw), 1)
            except ValueError:
                max_poll_interval_seconds = 10

        return cls(
            approvals_group=approvals_group,
            callback_url=callback_url,
            logic_app_url=logic_app_url,
            logic_app_url_secret_name=logic_app_url_name,
            callback_secret=callback_secret,
            callback_secret_name=callback_secret_name,
            timeout_seconds=timeout_seconds,
            expires_seconds=expires_seconds,
            poll_interval_seconds=poll_interval_seconds,
            max_poll_interval_seconds=max_poll_interval_seconds,
        )


def load_approval_workflow_config() -> ApprovalWorkflowConfig | None:
    """Helper to load approval workflow configuration if available."""

    return ApprovalWorkflowConfig.from_env()


@dataclass(frozen=True)
class MultiAgentConfig:
    """Configuration for the multi-agent orchestration flow."""

    triage_mode: str = "deterministic"
    recall_enabled: bool = True
    knowledge_enabled: bool = True

    @classmethod
    def from_env(cls) -> "MultiAgentConfig":
        triage_mode = (os.getenv("TRIAGE_MODE", "deterministic").strip() or "deterministic").lower()
        if triage_mode not in {"deterministic", "agentic"}:
            triage_mode = "deterministic"

        return cls(
            triage_mode=triage_mode,
            recall_enabled=_env_flag("ENABLE_RECALL", True),
            knowledge_enabled=_env_flag("ENABLE_KNOWLEDGE", True),
        )


def load_multi_agent_config() -> MultiAgentConfig:
    """Helper to load multi-agent orchestration configuration."""

    return MultiAgentConfig.from_env()
