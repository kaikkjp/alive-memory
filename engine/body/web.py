"""Web browse executor — real web search via OpenRouter web_search tool.

When the cortex decides to browse_web, this executor calls an LLM with
the web_search tool enabled, getting real search results summarized by
the model.  Results are injected into the content pool for reflection
on the next cycle.
"""

from __future__ import annotations

import uuid

import clock
from models.pipeline import ActionRequest, ActionResult
from body.executor import register
from body.rate_limiter import get_limiter_decision, limiter_payload, record_action
import db


@register('browse_web')
async def execute_browse_web(action: ActionRequest, visitor_id: str = None,
                             monologue: str = '') -> ActionResult:
    """Search the web for information."""
    result = ActionResult(action='browse_web', timestamp=clock.now_utc())

    query = (action.detail.get('content')
             or action.detail.get('query')
             or action.detail.get('text', '')).strip()
    if not query:
        result.success = False
        result.error = 'no search query provided'
        return result

    # Rate limit check
    limiter = await get_limiter_decision('browse_web')
    limiter_meta = limiter_payload(limiter)
    if not limiter['allowed']:
        result.success = False
        result.error = str(limiter['reason'])
        result.payload = dict(limiter_meta)
        return result

    # Channel kill switch
    from body.rate_limiter import is_channel_enabled
    if not await is_channel_enabled('web'):
        result.success = False
        result.error = 'web channel disabled'
        return result

    try:
        result_text = await _web_search(query)
    except Exception as e:
        result.success = False
        result.error = f'web search failed: {type(e).__name__}: {e}'
        result.payload = dict(limiter_meta)
        await record_action(
            'browse_web',
            success=False,
            error=result.error,
            **limiter_meta,
        )
        print(f"  [BrowseWeb] Search failed: {e}")
        return result

    # Truncate to ~6000 chars (same as read_content)
    if len(result_text) > 6000:
        result_text = result_text[:6000] + '\n[...truncated]'

    # Inject into content pool for reflection
    content_id = str(uuid.uuid4())
    pool_insert_ok = False
    try:
        from db.content import insert_pool_item
        await insert_pool_item({
            'id': content_id,
            'title': f'Web search: {query[:80]}',
            'content': result_text,
            'enriched_text': result_text,
            'source_channel': 'browse',
            'content_type': 'article',
            'status': 'ready',
        })
        pool_insert_ok = True
    except Exception as e:
        print(f"  [BrowseWeb] Failed to insert pool item: {e}")

    # MD write — conscious browse memory (independent of pool insert)
    try:
        import re as _re
        from memory_writer import get_memory_writer
        from memory_translator import scrub_numbers
        writer = get_memory_writer()
        slug = _re.sub(r'[^a-z0-9]+', '-', query.lower()).strip('-')[:50]
        date = clock.now().strftime('%Y-%m-%d')
        await writer.append_browse(date, slug,
            f"# Web search: {query}\n\n{scrub_numbers(result_text[:2000])}\n")
    except Exception as e:
        print(f"  [Memory] MD browse write failed: {e}")

    # Emit event only if pool insert succeeded — prevents dangling content_id refs
    if pool_insert_ok:
        from models.event import Event
        await db.append_event(Event(
            event_type='content_consumed',
            source='self',
            payload={
                'content_id': content_id,
                'title': f'Web search: {query[:80]}',
                'source': 'browse_web',
            },
        ))

    await record_action(
        'browse_web',
        success=True,
        **limiter_meta,
    )

    result.content = result_text
    result.payload = {
        'query': query,
        'content_id': content_id,
        'result_length': len(result_text),
        **limiter_meta,
    }
    result.side_effects.append('web_content_fetched')
    return result


async def _web_search(query: str) -> str:
    """Use OpenRouter with web_search tool to search the web."""
    from llm import complete as llm_complete

    response = await llm_complete(
        messages=[{
            'role': 'user',
            'content': f'Search the web for: {query}\n\nProvide a concise, informative summary of what you find. Include key facts, sources, and relevant details.',
        }],
        system='You are a research assistant. Search the web and provide a clear, factual summary.',
        call_site='browse',
        tools=[{'type': 'web_search', 'web_search': {'max_results': 5}}],
        max_tokens=2048,
        temperature=0.3,
    )

    # Extract text from response content blocks
    content = response.get('content', [])
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    texts.append(block['text'])
            elif isinstance(block, str):
                texts.append(block)
        return '\n'.join(texts) if texts else ''
    elif isinstance(content, str):
        return content
    return str(content)
