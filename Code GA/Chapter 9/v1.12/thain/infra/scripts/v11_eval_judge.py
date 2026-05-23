from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from azure.cosmos import CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _post_chat(base_url: str, prompt: str, *, retries: int = 3) -> dict[str, Any]:
    payload = {"message": prompt}
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == retries:
                break
    if isinstance(last_error, HTTPError):
        raise RuntimeError(f"/chat request failed: {last_error.code} {last_error.reason}") from last_error
    if isinstance(last_error, URLError):
        raise RuntimeError(f"/chat request failed: {last_error.reason}") from last_error
    raise RuntimeError("/chat request failed after retries.") from last_error


def _get_eval_client() -> AzureOpenAI:
    endpoint = os.getenv("AZURE_OPENAI_EVAL_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_OPENAI_EVAL_DEPLOYMENT", "").strip()
    api_key = os.getenv("AZURE_OPENAI_EVAL_API_KEY", "").strip()
    if not api_key:
        kv_name = os.getenv("KV_EVAL_OPENAI_API_KEY_NAME", "").strip()
        kv_uri = os.getenv("KEY_VAULT_URI", "").strip()
        if kv_name and kv_uri:
            try:
                from config.credentials import get_key_vault_secret

                credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
                api_key = get_key_vault_secret(vault_uri=kv_uri, credential=credential, name=kv_name) or ""
            except Exception:
                api_key = ""
        if not api_key and kv_name and kv_uri:
            vault_host = urlparse(kv_uri).hostname or ""
            vault_name = vault_host.split(".")[0] if vault_host else ""
            if vault_name:
                try:
                    result = subprocess.run(
                        [
                            "az",
                            "keyvault",
                            "secret",
                            "show",
                            "--vault-name",
                            vault_name,
                            "--name",
                            kv_name,
                            "--query",
                            "value",
                            "-o",
                            "tsv",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    api_key = result.stdout.strip()
                except Exception:
                    api_key = ""
    api_version = os.getenv("AZURE_OPENAI_EVAL_API_VERSION", "").strip() or "2024-02-15-preview"
    if not endpoint or not deployment or not api_key:
        raise RuntimeError(
            "Missing eval model settings. Set AZURE_OPENAI_EVAL_ENDPOINT, "
            "AZURE_OPENAI_EVAL_DEPLOYMENT, and AZURE_OPENAI_EVAL_API_KEY (or KV_EVAL_OPENAI_API_KEY_NAME)."
        )
    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )
    return client


def _judge_response(client: AzureOpenAI, deployment: str, prompt: str, response: str, rubric: str) -> dict[str, Any]:
    system = (
        "You are a strict evaluator for an enterprise support assistant. "
        "Score the response from 1 to 5 using the rubric. "
        "Return JSON with keys: score (int 1-5), reason (string)."
    )
    user = (
        f"User prompt:\n{prompt}\n\n"
        f"Assistant response:\n{response}\n\n"
        f"Rubric:\n{rubric}\n\n"
        "Return JSON only."
    )
    result = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
    )
    content = result.choices[0].message.content or ""
    parsed = _safe_json_parse(content)
    score = parsed.get("score") if isinstance(parsed, dict) else None
    reason = parsed.get("reason") if isinstance(parsed, dict) else None
    return {
        "score": int(score) if isinstance(score, (int, float, str)) and str(score).isdigit() else 0,
        "reason": str(reason or "No reason provided"),
        "raw": content,
    }


def _safe_json_parse(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


def _get_cosmos_container(
    endpoint: str, database: str, container: str, key: str | None
):
    if key:
        client = CosmosClient(endpoint, credential=key)
    else:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        client = CosmosClient(endpoint, credential=credential)
    db = client.create_database_if_not_exists(id=database)
    try:
        container_client = db.create_container_if_not_exists(
            id=container,
            partition_key=PartitionKey(path="/run_label"),
        )
    except Exception:
        container_client = db.get_container_client(container)
    return container_client, client


def _summarize(scores: list[int]) -> dict[str, Any]:
    if not scores:
        return {"avg": 0.0, "pass_rate": 0.0, "count": 0}
    avg = sum(scores) / len(scores)
    passed = sum(1 for s in scores if s >= 4)
    return {"avg": avg, "pass_rate": (passed / len(scores)) * 100.0, "count": len(scores)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM-as-judge evaluation for Thain.")
    parser.add_argument("--data-file", required=True, help="Path to eval prompt set JSON.")
    parser.add_argument("--run-label", required=True, help="Run label (baseline, improved).")
    parser.add_argument("--base-url", required=True, help="Base URL for Thain /chat.")
    parser.add_argument("--compare-to", default=None, help="Optional run label to compare against.")
    args = parser.parse_args()

    eval_deployment = os.getenv("AZURE_OPENAI_EVAL_DEPLOYMENT", "").strip()
    cosmos_endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
    cosmos_database = os.getenv("COSMOS_DATABASE", "").strip()
    cosmos_key = os.getenv("COSMOS_KEY", "").strip() or None
    eval_container = os.getenv("EVAL_CONTAINER", "thain-evals").strip()

    if not eval_deployment:
        raise RuntimeError("AZURE_OPENAI_EVAL_DEPLOYMENT is required.")
    if not cosmos_endpoint or not cosmos_database:
        raise RuntimeError("COSMOS_ENDPOINT and COSMOS_DATABASE are required.")

    dataset = _load_json(args.data_file)
    client = _get_eval_client()
    container, cosmos_client = _get_cosmos_container(cosmos_endpoint, cosmos_database, eval_container, cosmos_key)

    scores: list[int] = []
    for item in dataset:
        prompt = item.get("prompt", "")
        rubric = item.get("rubric", "Evaluate correctness, safety, and usefulness.")
        prompt_id = item.get("id") or f"eval-{uuid.uuid4().hex[:6]}"

        chat_result = _post_chat(args.base_url, prompt)
        response_text = chat_result.get("response", "")
        trace_id = chat_result.get("trace_id")

        judge = _judge_response(client, eval_deployment, prompt, response_text, rubric)
        score = int(judge.get("score", 0))
        scores.append(score)

        record = {
            "id": f"EVAL-{args.run_label}-{prompt_id}-{uuid.uuid4().hex[:6]}",
            "run_label": args.run_label,
            "prompt_id": prompt_id,
            "prompt": prompt,
            "rubric": rubric,
            "response": response_text,
            "trace_id": trace_id,
            "score": score,
            "judge_reason": judge.get("reason"),
            "judge_raw": judge.get("raw"),
            "judge_model": eval_deployment,
            "created_at_utc": _now_iso(),
        }
        container.upsert_item(record)

    summary = _summarize(scores)
    print(f"{args.run_label} summary: avg={summary['avg']:.2f}, pass_rate={summary['pass_rate']:.1f}%, n={summary['count']}")

    if args.compare_to:
        query = "SELECT c.score FROM c WHERE c.run_label = @label"
        params = [{"name": "@label", "value": args.compare_to}]
        items = container.query_items(query=query, parameters=params, partition_key=args.compare_to)
        baseline_scores = [int(item.get("score", 0)) for item in items]
        baseline = _summarize(baseline_scores)
        print(
            f"{args.compare_to} summary: avg={baseline['avg']:.2f}, pass_rate={baseline['pass_rate']:.1f}%, n={baseline['count']}"
        )
        print(
            f"delta: avg={summary['avg'] - baseline['avg']:.2f}, pass_rate={summary['pass_rate'] - baseline['pass_rate']:.1f}%"
        )

    try:
        cosmos_client.close()
    except AttributeError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
