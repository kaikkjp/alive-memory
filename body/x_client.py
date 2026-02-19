"""Low-level X/Twitter API wrapper.

Extends the pattern from workers/x_poster.py for live posting, replying,
media upload, and mention fetching.  Uses tweepy with OAuth credentials.
All sync tweepy calls are wrapped in asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import os


def _get_client():
    """Create an authenticated tweepy Client."""
    try:
        import tweepy
    except ImportError:
        raise RuntimeError(
            'tweepy not installed. Install with: pip install tweepy'
        )

    api_key = os.environ.get('X_API_KEY')
    api_secret = os.environ.get('X_API_SECRET')
    access_token = os.environ.get('X_ACCESS_TOKEN')
    access_secret = os.environ.get('X_ACCESS_SECRET')

    if not all([api_key, api_secret, access_token, access_secret]):
        raise ValueError('X API credentials not configured')

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
    )


def _get_api_v1():
    """Create tweepy API v1.1 instance for media upload."""
    try:
        import tweepy
    except ImportError:
        raise RuntimeError('tweepy not installed')

    api_key = os.environ.get('X_API_KEY')
    api_secret = os.environ.get('X_API_SECRET')
    access_token = os.environ.get('X_ACCESS_TOKEN')
    access_secret = os.environ.get('X_ACCESS_SECRET')

    if not all([api_key, api_secret, access_token, access_secret]):
        raise ValueError('X API credentials not configured')

    auth = tweepy.OAuth1UserHandler(
        api_key, api_secret, access_token, access_secret,
    )
    return tweepy.API(auth)


async def post_tweet(text: str) -> dict:
    """Post a tweet. Returns {success, x_post_id, error}."""
    try:
        client = _get_client()

        def _post():
            return client.create_tweet(text=text[:280])

        response = await asyncio.to_thread(_post)
        x_post_id = str(response.data['id'])
        print(f"  [XClient] Posted tweet {x_post_id}")
        return {'success': True, 'x_post_id': x_post_id}

    except Exception as e:
        error_msg = f'{type(e).__name__}: {e}'
        print(f"  [XClient] Post failed: {error_msg}")
        return {'success': False, 'error': error_msg}


async def reply_tweet(text: str, reply_to_id: str) -> dict:
    """Reply to a tweet. Returns {success, x_post_id, error}."""
    try:
        client = _get_client()

        def _reply():
            return client.create_tweet(
                text=text[:280],
                in_reply_to_tweet_id=reply_to_id,
            )

        response = await asyncio.to_thread(_reply)
        x_post_id = str(response.data['id'])
        print(f"  [XClient] Reply {x_post_id} to {reply_to_id}")
        return {'success': True, 'x_post_id': x_post_id}

    except Exception as e:
        error_msg = f'{type(e).__name__}: {e}'
        print(f"  [XClient] Reply failed: {error_msg}")
        return {'success': False, 'error': error_msg}


async def post_tweet_with_media(text: str, image_path: str) -> dict:
    """Post a tweet with an image. Returns {success, x_post_id, error}."""
    try:
        api_v1 = _get_api_v1()
        client = _get_client()

        def _upload_and_post():
            media = api_v1.media_upload(image_path)
            return client.create_tweet(
                text=text[:280],
                media_ids=[media.media_id],
            )

        response = await asyncio.to_thread(_upload_and_post)
        x_post_id = str(response.data['id'])
        print(f"  [XClient] Posted tweet with media {x_post_id}")
        return {'success': True, 'x_post_id': x_post_id}

    except Exception as e:
        error_msg = f'{type(e).__name__}: {e}'
        print(f"  [XClient] Media post failed: {error_msg}")
        return {'success': False, 'error': error_msg}


async def fetch_mentions(since_id: str = None) -> list[dict]:
    """Fetch recent mentions. Returns list of mention dicts."""
    bearer_token = os.environ.get('X_BEARER_TOKEN')
    if not bearer_token:
        return []

    try:
        import tweepy

        def _fetch():
            client = tweepy.Client(bearer_token=bearer_token)
            bot_user_id = os.environ.get('X_BOT_USER_ID', '')

            kwargs = {
                'id': bot_user_id,
                'tweet_fields': ['author_id', 'created_at', 'text', 'conversation_id'],
                'max_results': 20,
            }
            if since_id:
                kwargs['since_id'] = since_id

            return client.get_users_mentions(**kwargs)

        response = await asyncio.to_thread(_fetch)

        if not response or not response.data:
            return []

        mentions = []
        for tweet in response.data:
            mentions.append({
                'id': str(tweet.id),
                'author_id': str(tweet.author_id or 'unknown'),
                'text': tweet.text or '',
                'conversation_id': str(tweet.conversation_id or tweet.id),
                'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
            })

        return mentions

    except Exception as e:
        print(f"  [XClient] Mention fetch failed: {type(e).__name__}: {e}")
        return []
