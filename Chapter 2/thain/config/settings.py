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
def load_config() -> AzureAgentConfig:
    """Helper to load Azure configuration from the environment."""

    return AzureAgentConfig.from_env()
