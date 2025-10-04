"""
Deepseek API client helper
Reads DEEPSEEK_API_KEY from environment at call time and provides a simple search wrapper.

This file intentionally does NOT store any secrets. Put your key in the environment or a local `.env` file
that is listed in `.gitignore` (we provide `.env.example` as a template).
"""
import os
from typing import Any, Dict
import requests


def get_api_key() -> str:
    """Return the DEEPSEEK_API_KEY from environment or raise if missing."""
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        raise RuntimeError('DEEPSEEK_API_KEY not set in environment')
    return api_key


def is_configured() -> bool:
    return bool(os.getenv('DEEPSEEK_API_KEY'))


def get_headers() -> Dict[str, str]:
    api_key = get_api_key()
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }


def search(query: str, limit: int = 5) -> Any:
    """Perform a search request against the Deepseek API.

    NOTE: Replace the default ENDPOINT with the real Deepseek endpoint if needed.
    """
    endpoint = os.getenv('DEEPSEEK_API_ENDPOINT', 'https://api.deepseek.example/v1/search')
    payload = {
        'query': query,
        'limit': limit
    }

    resp = requests.post(endpoint, json=payload, headers=get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()
