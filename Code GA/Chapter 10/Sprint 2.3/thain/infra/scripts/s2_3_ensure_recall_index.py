from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_search_config
from memory.search_client import AzureSemanticSearchClient
from services.embedding import EmbeddingService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensure the semantic recall index exists for reliability validation."
    )
    parser.add_argument(
        "--env-file",
        default=".env.dev",
        help="Path to env file to load before running (default: .env.dev).",
    )
    return parser.parse_args()


async def _run() -> int:
    cfg = load_search_config()
    if not cfg:
        print("Semantic recall is disabled (AZURE_SEARCH_MODE=off). Skipping recall index ensure.")
        return 0

    embedding_service = EmbeddingService(
        endpoint=cfg.embedding_endpoint,
        deployment=cfg.embedding_deployment,
        api_version=cfg.embedding_api_version,
        api_key=cfg.embedding_api_key,
    )
    search_client = AzureSemanticSearchClient(cfg)
    try:
        probe_embedding = await embedding_service.embed("thain-reliability-index-probe")
        dimensions = len(probe_embedding or [])
        if dimensions <= 0:
            raise RuntimeError("Embedding probe returned an empty vector.")
        await search_client.ensure_index(dimensions)
        print(f"Recall index ready: {cfg.index_name} (vector dimensions: {dimensions})")
        return 0
    except Exception as exc:
        print(f"Failed to ensure recall index '{cfg.index_name}': {exc}", file=sys.stderr)
        return 1
    finally:
        with suppress(Exception):
            await embedding_service.close()
        with suppress(Exception):
            await search_client.close()


def main() -> int:
    args = _parse_args()
    env_path = Path(args.env_file)
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=False)
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
