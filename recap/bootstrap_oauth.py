"""One-shot CLI to seed OAuth client credentials into the OS keyring.

Prerequisite step for the plugin's Calendar OAuth Connect button. After
running this once per provider, the plugin Settings' Connect button can
initiate the browser auth dance without 400'ing on a missing
client_id/client_secret lookup.

Usage:
    uv run python -m recap.bootstrap_oauth zoho --client-id ... --client-secret ...
    uv run python -m recap.bootstrap_oauth google --client-id ... --client-secret ...

Where to get credentials:

- **Zoho Calendar**: https://api-console.zoho.com -> your OAuth "Server-based
  Applications" client -> Client Secret tab shows both Client ID and Client
  Secret. Authorized Redirect URI on the Zoho app side must be
  ``http://localhost:8399/callback`` to match the daemon's OAuthManager.
- **Google Calendar**: https://console.cloud.google.com -> your project ->
  APIs & Services -> Credentials -> your "OAuth 2.0 Client ID" (type: Web
  application or Desktop app) -> shows Client ID and Client Secret.
  Authorized redirect URI must be ``http://localhost:8399/callback``.

This tool just stores the credentials; it does NOT start the OAuth flow.
The flow itself happens in the plugin Settings -> Connect button, which
POSTs /api/oauth/<provider>/start against the daemon.
"""
from __future__ import annotations

import argparse
import sys

from recap.daemon.credentials import (
    delete_credential,
    get_credential,
    store_credential,
)

_PROVIDERS = ("zoho", "google")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m recap.bootstrap_oauth",
        description=(
            "Seed OAuth client credentials into the OS keyring so the "
            "plugin's Calendar Connect button can initiate auth. "
            "Run once per provider after registering an OAuth app."
        ),
    )
    parser.add_argument(
        "provider",
        choices=_PROVIDERS,
        help="OAuth provider identifier",
    )
    parser.add_argument(
        "--client-id",
        required=False,
        help="OAuth client ID from the provider's developer console",
    )
    parser.add_argument(
        "--client-secret",
        required=False,
        help="OAuth client secret from the provider's developer console",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print whether client_id/client_secret are currently stored (does not print values)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Remove stored client_id/client_secret for this provider",
    )
    args = parser.parse_args(argv)

    if args.show:
        cid = get_credential(args.provider, "client_id")
        csec = get_credential(args.provider, "client_secret")
        print(f"provider: {args.provider}")
        print(f"  client_id:     {'<set>' if cid else '<missing>'}")
        print(f"  client_secret: {'<set>' if csec else '<missing>'}")
        return 0

    if args.delete:
        delete_credential(args.provider, "client_id")
        delete_credential(args.provider, "client_secret")
        print(f"Deleted client_id/client_secret for {args.provider}")
        return 0

    if not args.client_id or not args.client_secret:
        parser.error("--client-id and --client-secret are required unless --show or --delete is used")

    store_credential(args.provider, "client_id", args.client_id)
    store_credential(args.provider, "client_secret", args.client_secret)
    print(f"Stored client_id/client_secret for {args.provider} in the OS keyring.")
    print(
        "Next step: in Obsidian, open Settings -> Recap -> "
        f"find the {args.provider.capitalize()} Calendar row -> click Connect.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
