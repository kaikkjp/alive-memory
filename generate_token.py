#!/usr/bin/env python3
"""Generate invite tokens for the Shopkeeper's chat gate.

Usage:
    python generate_token.py --name "Yuki" --uses 10 --expires 7d
    python generate_token.py --name "Guest" --uses 1
    python generate_token.py --name "Staff" (unlimited uses, no expiry)
"""

import argparse
import asyncio
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

import db


def parse_duration(s: str) -> timedelta:
    """Parse a duration string like '7d', '24h', '30m' into a timedelta."""
    match = re.match(r'^(\d+)([dhm])$', s.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(
            f"Invalid duration '{s}'. Use format like '7d', '24h', '30m'."
        )
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 'd':
        return timedelta(days=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    raise argparse.ArgumentTypeError(f"Unknown unit '{unit}'.")


async def main():
    parser = argparse.ArgumentParser(
        description='Generate a chat invite token for the Shopkeeper window.'
    )
    parser.add_argument(
        '--name', required=True,
        help='Display name for the token holder (e.g., "Yuki").'
    )
    parser.add_argument(
        '--uses', type=int, default=None,
        help='Number of chat messages allowed. Omit for unlimited.'
    )
    parser.add_argument(
        '--expires', type=parse_duration, default=None,
        help='Token expiry duration (e.g., 7d, 24h, 30m). Omit for no expiry.'
    )

    args = parser.parse_args()

    # Generate token
    token = secrets.token_urlsafe(16)

    # Compute expiry
    expires_at = None
    if args.expires:
        expires_at = datetime.now(timezone.utc) + args.expires

    # Initialize DB and create token
    await db.init_db()
    await db.create_chat_token(
        token=token,
        display_name=args.name,
        uses_remaining=args.uses,
        expires_at=expires_at,
    )
    await db.close_db()

    # Output
    print(f"\n  Token generated successfully.\n")
    print(f"  Token:   {token}")
    print(f"  Name:    {args.name}")
    print(f"  Uses:    {'unlimited' if args.uses is None else args.uses}")
    if expires_at:
        print(f"  Expires: {expires_at.isoformat()}")
    else:
        print(f"  Expires: never")
    print()


if __name__ == '__main__':
    asyncio.run(main())
