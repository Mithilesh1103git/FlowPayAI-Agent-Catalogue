"""Centralized Nebius Token Factory / NVIDIA Nemotron configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
# Nemotron 3 Super is retired from Nebius Serverless on 2026-11-09.
# Use the provider-named replacement instead.
DEFAULT_MODEL = "nvidia/Nemotron-3.5-Super-VL"

# All LLM-backed agents use one provider/model by default. Individual model
# overrides remain available for later routing or cost/latency experiments.
MODEL_CONFIG: dict[str, dict[str, object]] = {
    "planner": {
        "model": os.getenv("PLANNER_MODEL", os.getenv("NEBIUS_MODEL", DEFAULT_MODEL)),
        "temperature": float(os.getenv("PLANNER_TEMPERATURE", "0")),
    },
    "research": {
        "model": os.getenv("RESEARCH_MODEL", os.getenv("NEBIUS_MODEL", DEFAULT_MODEL)),
        "temperature": float(os.getenv("RESEARCH_TEMPERATURE", "0")),
    },
    "comparison": {
        "model": os.getenv(
            "COMPARISON_MODEL", os.getenv("NEBIUS_MODEL", DEFAULT_MODEL)
        ),
        "temperature": float(os.getenv("COMPARISON_TEMPERATURE", "0")),
    },
    "advisor": {
        "model": os.getenv("ADVISOR_MODEL", os.getenv("NEBIUS_MODEL", DEFAULT_MODEL)),
        "temperature": float(os.getenv("ADVISOR_TEMPERATURE", "0.3")),
    },
}


def get_llm(agent_name: str) -> ChatOpenAI:
    """Create a LangChain chat model using Nebius' OpenAI-compatible API."""
    if agent_name not in MODEL_CONFIG:
        raise ValueError(f"Unknown agent: {agent_name}")

    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NEBIUS_API_KEY is missing. Add your Nebius Token Factory API key "
            "to the environment or .env file."
        )

    config = MODEL_CONFIG[agent_name]
    model_name = str(config["model"]).strip()
    if not model_name:
        raise ValueError(f"Model not configured for {agent_name}")

    return ChatOpenAI(
        model=model_name,
        temperature=float(config["temperature"]),
        api_key=api_key,
        base_url=os.getenv("NEBIUS_BASE_URL", DEFAULT_BASE_URL),
        timeout=float(os.getenv("NEBIUS_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("NEBIUS_MAX_RETRIES", "2")),
    )
