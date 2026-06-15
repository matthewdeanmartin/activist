import logging
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["rank_policy_links", "select_model"]

# Local, no-API-key model that ships as a small llm plugin (llm-smollm2).
# Used when no OpenRouter model/key is configured, so this works offline/CI.
FALLBACK_MODEL = "SmolLM2"

PROMPT_TEMPLATE = """Below is the text of a Mastodon instance's "About" page, \
followed by a list of links found on that page.

Identify which of these links, if any, point to the instance's Terms of \
Service, Privacy Policy, or Community Guidelines / Rules document (these are \
sometimes hosted on a different domain than the instance itself).

Reply with the matching URL(s) only, one per line, copied exactly as given \
below. If none of the links match, reply with NONE. Do not invent or modify \
any URL.

About page text:
{about_text}

Links:
{links}
"""


def select_model(override: Optional[str] = None) -> str:
    """Pick which `llm` model to use.

    Priority: explicit `override` > `OPENROUTER_MODEL` from the environment
    (if the openrouter llm plugin + key are configured) > local fallback
    model that needs no API key.
    """
    if override:
        return override

    openrouter_model = os.environ.get("OPENROUTER_MODEL")
    if openrouter_model and os.environ.get("OPENROUTER_API_KEY"):
        # llm's openrouter plugin expects model ids prefixed with "openrouter/"
        if openrouter_model.startswith("openrouter/"):
            return openrouter_model
        return f"openrouter/{openrouter_model}"

    return FALLBACK_MODEL


def rank_policy_links(
    about_text: str,
    links: List[Tuple[str, str]],
    model: Optional[str] = None,
    timeout: float = 60.0,
) -> List[str]:
    """Ask the `llm` CLI which of `links` are policy/ToS/privacy pages.

    `links` is a list of (text, url) pairs. Returns the subset of URLs (from
    `links`) that the model selected, in the order it returned them. Any URL
    the model returns that is NOT in `links` is dropped -- never follow a
    link the model invented.

    Returns an empty list if the `llm` binary is missing, the subprocess
    fails, or the response is unparseable/NONE. This is a best-effort
    enrichment, never a hard failure.
    """
    if not links:
        return []

    if shutil.which("llm") is None:
        logger.info("`llm` CLI not found on PATH; skipping LLM link ranking")
        return []

    candidate_urls = {url for _, url in links}
    links_block = "\n".join(f"({text}) {url}" for text, url in links)
    prompt = PROMPT_TEMPLATE.format(about_text=about_text[:4000], links=links_block)

    chosen_model = select_model(model)

    try:
        result = subprocess.run(
            ["llm", "-m", chosen_model, prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"`llm` invocation failed: {e}")
        return []

    if result.returncode != 0:
        logger.warning(f"`llm` exited with {result.returncode}: {result.stderr.strip()}")
        return []

    output = result.stdout.strip()
    if not output or output.upper() == "NONE":
        return []

    selected: List[str] = []
    for line in output.splitlines():
        candidate = line.strip()
        if candidate in candidate_urls and candidate not in selected:
            selected.append(candidate)

    return selected
