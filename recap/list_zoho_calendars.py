"""Small diagnostic to list the authenticated user's Zoho calendars.

Zoho does not have a "primary" fallback like Google, so the daemon needs
an explicit calendar UID to sync against. Run this after completing the
Zoho OAuth flow to discover the UIDs and pick one for ``calendars.zoho.calendar-id``
in config.yaml.

Usage:
    uv run python -m recap.list_zoho_calendars
"""
from __future__ import annotations

import asyncio
import sys

import aiohttp

from recap.daemon.credentials import get_credential


async def main() -> int:
    token = get_credential("zoho", "access_token")
    if not token:
        print(
            "No Zoho access_token in keyring. Complete the OAuth Connect flow "
            "in the Obsidian plugin first.",
            file=sys.stderr,
        )
        return 1

    url = "https://calendar.zoho.com/api/v1/calendars"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(f"Zoho API returned {resp.status}: {body}", file=sys.stderr)
                return 1
            data = await resp.json()

    calendars = data.get("calendars", [])
    if not calendars:
        print("No calendars returned by the Zoho API.")
        return 0

    print(f"Found {len(calendars)} Zoho calendar(s):\n")
    for cal in calendars:
        default_marker = "  [DEFAULT]" if cal.get("isdefault") else ""
        print(f"  name: {cal.get('name', '<unnamed>')}{default_marker}")
        print(f"  uid:  {cal.get('uid', '<missing>')}")
        print()

    print(
        "Copy the uid of the calendar you want Recap to sync, then edit "
        "config.yaml and add it under calendars.zoho.calendar-id:"
    )
    print("\n  calendars:")
    print("    zoho:")
    print("      org: \"disbursecloud\"")
    print('      calendar-id: "<the uid above>"')
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
