"""Pipeline step shared helpers — async runner & LLM wrappers"""

import asyncio


def _run_async(coro):
    """Run an async coroutine from sync code.

    Uses asyncio.run() in worker (no running loop).
    Falls back to a thread pool when called from FastAPI test endpoint
    (event loop already running).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside an event loop (e.g. FastAPI) — run in a new thread to avoid blocking
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _llm_chat(messages, response_format=None):
    """Create LLM client, call chat, close client properly."""
    from app.services.analyzers.llm_analyzer import LLMAnalyzer
    analyzer = LLMAnalyzer()
    try:
        return await analyzer.client.chat.completions.create(
            model=analyzer.model,
            messages=messages,
            response_format=response_format,
        )
    finally:
        await analyzer.client.close()


async def _llm_analyze(text, prompt_tpl):
    """Create LLM analyzer, run analysis, close client properly."""
    from app.services.analyzers.llm_analyzer import LLMAnalyzer
    analyzer = LLMAnalyzer()
    try:
        return await analyzer.analyze(text, prompt_tpl)
    finally:
        await analyzer.client.close()
