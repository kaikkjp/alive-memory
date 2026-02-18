"""X/Twitter posting worker (TASK-057).

Posts approved drafts to X via the v2 API and fetches replies.
Called from dashboard approve endpoint — not a background loop.

Uses tweepy for OAuth and API calls. Sync tweepy calls are wrapped
in asyncio.to_thread() to stay non-blocking.

Environment variables:
    X_API_KEY         — consumer key (app credentials)
    X_API_SECRET      — consumer secret (app credentials)
    X_ACCESS_TOKEN    — user access token (for posting)
    X_ACCESS_SECRET   — user access token secret (for posting)
    X_BEARER_TOKEN    — app-only bearer token (for reading replies)
"""

import asyncio
import os

import clock
import db
from models.event import Event


async def post_tweet(draft_id: str) -> dict:
    """Post an approved draft to X. Returns result dict.

    Reads draft from DB, validates status, posts via tweepy Client.
    On success: marks posted with x_post_id.
    On failure: marks failed with error message.
    """
    draft = await db.get_draft_by_id(draft_id)
    if not draft:
        return {'success': False, 'error': 'draft not found'}
    if draft['status'] != 'approved':
        return {'success': False, 'error': f'draft status is {draft["status"]}, expected approved'}

    api_key = os.environ.get('X_API_KEY')
    api_secret = os.environ.get('X_API_SECRET')
    access_token = os.environ.get('X_ACCESS_TOKEN')
    access_secret = os.environ.get('X_ACCESS_SECRET')

    if not all([api_key, api_secret, access_token, access_secret]):
        await db.mark_post_failed(draft_id, 'X API credentials not configured')
        return {'success': False, 'error': 'X API credentials not configured'}

    try:
        import tweepy

        def _post():
            client = tweepy.Client(
                consumer_key=api_key,
                consumer_secret=api_secret,
                access_token=access_token,
                access_token_secret=access_secret,
            )
            return client.create_tweet(text=draft['draft_text'])

        response = await asyncio.to_thread(_post)
        x_post_id = str(response.data['id'])
        await db.mark_posted(draft_id, x_post_id)
        print(f"  [XPoster] Posted tweet {x_post_id} for draft {draft_id[:8]}")
        return {'success': True, 'x_post_id': x_post_id}

    except Exception as e:
        error_msg = f'{type(e).__name__}: {e}'
        await db.mark_post_failed(draft_id, error_msg)
        print(f"  [XPoster] Failed to post: {error_msg}")
        return {'success': False, 'error': error_msg}


async def fetch_replies(x_post_id: str, since_id: str = None) -> list[dict]:
    """Fetch replies to a posted tweet and create visitor events.

    Basic structure — full webhook/polling implementation is a follow-up.
    Converts X replies into visitor_message events in the inbox.
    """
    bearer_token = os.environ.get('X_BEARER_TOKEN')
    if not bearer_token:
        print("  [XPoster] X_BEARER_TOKEN not set, skipping reply fetch")
        return []

    try:
        import tweepy

        def _fetch():
            client = tweepy.Client(bearer_token=bearer_token)
            return client.search_recent_tweets(
                query=f'conversation_id:{x_post_id}',
                tweet_fields=['author_id', 'created_at', 'text'],
                max_results=10,
            )

        response = await asyncio.to_thread(_fetch)

        if not response.data:
            return []

        events = []
        for tweet in response.data:
            author_id = tweet.author_id or 'unknown'
            event = Event(
                event_type='visitor_message',
                source=f'x:{author_id}',
                payload={
                    'text': tweet.text or '',
                    'channel': 'x',
                    'x_tweet_id': str(tweet.id),
                    'x_author_id': str(author_id),
                    'in_reply_to': x_post_id,
                },
            )
            await db.append_event(event)
            await db.inbox_add(event.id)
            events.append({'id': event.id, 'author': str(author_id), 'text': tweet.text})
            print(f"  [XPoster] Reply ingested from x:{author_id}")

        return events

    except Exception as e:
        print(f"  [XPoster] Exception fetching replies: {type(e).__name__}: {e}")
        return []
