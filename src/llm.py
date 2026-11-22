"""One place that decides which model answers.

get_llm() returns a main model plus backups (LangChain `with_fallbacks`).
If the main model fails or runs out of free quota, the request moves on to
the next one automatically. The LangSmith trace shows which model answered.

Model names change often: set them in .env (see .env.example) instead of
editing code.
"""

import os

from dotenv import load_dotenv

load_dotenv()

from langchain_core.rate_limiters import InMemoryRateLimiter  # noqa: E402

# Free plans limit requests per minute (Gemini Flash-Lite: 15).
# The website sends one request at a time, so it needs no brake (0 = off) and answers fast.
# The evaluation sends dozens in a row, so eval/run_eval.py sets 0.2/sec = 12 per minute.
_RPS = float(os.getenv("REQUESTS_PER_SECOND", "0") or 0)
RATE_LIMITER = (InMemoryRateLimiter(requests_per_second=_RPS, check_every_n_seconds=0.1)
                if _RPS > 0 else None)
TIMEOUT = 25  # seconds: a slow or stuck model is dropped and the backup takes over


def _gemini(name: str):
    if not os.getenv("GOOGLE_API_KEY") or not name:
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI
    # max_retries=0 + timeout: when a free model is busy, move on to the backup at once
    return ChatGoogleGenerativeAI(model=name, temperature=0, max_retries=0, timeout=TIMEOUT,
                                  rate_limiter=RATE_LIMITER)


def _groq(vision: bool):
    if not os.getenv("GROQ_API_KEY"):
        return None
    from langchain_groq import ChatGroq
    name = os.getenv("GROQ_VISION_MODEL") if vision else os.getenv("GROQ_MODEL")
    if not name:
        return None
    return ChatGroq(model=name, temperature=0, max_retries=0, timeout=TIMEOUT, rate_limiter=RATE_LIMITER)


def _openrouter(vision: bool):
    if not os.getenv("OPENROUTER_API_KEY"):
        return None
    from langchain_openai import ChatOpenAI
    name = os.getenv("OPENROUTER_VISION_MODEL") if vision else os.getenv("OPENROUTER_MODEL")
    if not name:
        return None
    return ChatOpenAI(model=name, temperature=0, max_retries=0, timeout=TIMEOUT, api_key=os.getenv("OPENROUTER_API_KEY"),
                      base_url="https://openrouter.ai/api/v1", rate_limiter=RATE_LIMITER)


def _ollama(vision: bool):
    name = os.getenv("OLLAMA_VISION_MODEL") if vision else os.getenv("OLLAMA_MODEL")
    if not name:
        return None
    from langchain_ollama import ChatOllama
    return ChatOllama(model=name, temperature=0)  # local: no limit needed


def get_models(vision: bool = False) -> list:
    """All configured models, in order. Image steps get only image-capable models."""
    models = [
        # Fastest first. Each Gemini model has its own free daily quota, so when one runs
        # out the next one (same key) takes over. GEMINI_BACKUP_MODEL may list several, comma-separated.
        _gemini(os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")),
        *[_gemini(n.strip()) for n in os.getenv(
            "GEMINI_BACKUP_MODEL",
            "gemini-flash-lite-latest,gemini-3.6-flash,gemma-4-26b-a4b-it").split(",")],
        _groq(vision), _openrouter(vision), _ollama(vision),
    ]
    return [m for m in models if m is not None]


def get_llm(vision: bool = False):
    """Main model with automatic backups."""
    models = get_models(vision)
    if not models:
        raise RuntimeError("לא הוגדר אף מודל. מלאי מפתח אחד לפחות בקובץ .env")
    return models[0].with_fallbacks(models[1:]) if len(models) > 1 else models[0]


def get_structured_llm(schema, vision: bool = False):
    """Same as get_llm, but every model returns the given Pydantic schema."""
    models = [m.with_structured_output(schema) for m in get_models(vision)]
    if not models:
        raise RuntimeError("לא הוגדר אף מודל. מלאי מפתח אחד לפחות בקובץ .env")
    return models[0].with_fallbacks(models[1:]) if len(models) > 1 else models[0]
