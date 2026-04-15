"""Phase 4 contract integration: pairing → Bearer → journal → /api/events
backfill → WS live → /api/config GET+PATCH.

Unlike the per-endpoint tests, this one brings up a real ``Daemon`` with
its full HTTP server (via ``daemon.start``) and exercises each Phase 4
contract against the live TCP socket, to catch regressions that only
show up when the middleware, app wiring, and journal all run together.
"""
from __future__ import annotations

import asyncio
import pathlib

import aiohttp
import pytest

from recap.daemon.service import Daemon
from tests.conftest import (
    MINIMAL_API_CONFIG_YAML,
    build_daemon_callbacks,
    make_daemon_config,
    minimal_daemon_args,
)


@pytest.mark.asyncio
async def test_phase4_contracts_end_to_end(tmp_path: pathlib.Path) -> None:
    cfg = make_daemon_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        MINIMAL_API_CONFIG_YAML.format(
            vault=(tmp_path / "vault").as_posix(),
            rec=(tmp_path / "rec").as_posix(),
        ),
        encoding="utf-8",
    )
    # The marker comment is the first line of MINIMAL_API_CONFIG_YAML;
    # capture it so we can assert comment preservation after PATCH.
    marker = "# Top-of-file marker comment (do not remove)"
    assert marker in config_path.read_text(encoding="utf-8")

    daemon = Daemon(cfg, config_path=config_path)
    callbacks = build_daemon_callbacks(daemon)
    # ``build_daemon_callbacks`` owns the token the middleware will
    # enforce; read it from the dict rather than hard-coding, so a
    # refactor of the fixture doesn't silently desync from the test.
    token = callbacks["auth_token"]

    await daemon.start(args=minimal_daemon_args(), callbacks=callbacks)
    try:
        assert daemon.port is not None
        base = f"http://127.0.0.1:{daemon.port}"
        ws_base = f"ws://127.0.0.1:{daemon.port}"
        bearer = {"Authorization": f"Bearer {token}"}

        async with aiohttp.ClientSession() as session:
            # ---- Pairing: one-shot window, second call 404 ----
            daemon.pairing.open()
            async with session.get(f"{base}/bootstrap/token") as resp:
                assert resp.status == 200
                body = await resp.json()
                assert body["token"] == token
            async with session.get(f"{base}/bootstrap/token") as resp:
                assert resp.status == 404

            # ---- Bearer gate on /api/* ----
            async with session.get(f"{base}/api/events") as resp:
                assert resp.status == 401
            async with session.get(
                f"{base}/api/events", headers=bearer,
            ) as resp:
                assert resp.status == 200

            # ---- Journal tail: pairing + startup entries present ----
            journal_events = {
                e.get("event") for e in daemon.event_journal.tail(limit=100)
            }
            assert "daemon_started" in journal_events
            assert "pairing_opened" in journal_events
            assert "pairing_token_issued" in journal_events

            # ---- /api/events since-filter ----
            async with session.get(
                f"{base}/api/events?limit=100", headers=bearer,
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                before_entries = data["entries"]
            assert any(
                e.get("event") == "pairing_opened" for e in before_entries
            )
            middle_ts = before_entries[-1]["ts"]

            # Distinct microsecond: the journal uses µs precision but
            # two appends inside the same instant could collide.
            await asyncio.sleep(0.01)
            daemon.emit_event(
                "info", "post_test_marker", "after middle_ts",
            )

            async with session.get(
                f"{base}/api/events?since={middle_ts}", headers=bearer,
            ) as resp:
                assert resp.status == 200
                since_data = await resp.json()
            since_events = [e.get("event") for e in since_data["entries"]]
            assert "post_test_marker" in since_events
            assert "pairing_opened" not in since_events

            # ---- WebSocket live stream ----
            async with session.ws_connect(
                f"{ws_base}/api/ws?token={token}",
            ) as ws:
                # Give the server a moment to finalize the subscription.
                await asyncio.sleep(0.05)
                daemon.emit_event(
                    "info", "ws_live_test", "streamed",
                )

                saw_ws_live = False
                for _ in range(10):
                    msg = await asyncio.wait_for(
                        ws.receive(), timeout=2.0,
                    )
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = msg.json()
                    if data.get("event") != "journal_entry":
                        continue
                    entry = data.get("entry") or {}
                    if entry.get("event") == "ws_live_test":
                        saw_ws_live = True
                        break
                assert saw_ws_live, (
                    "WebSocket did not receive journal_entry for "
                    "ws_live_test within timeout"
                )

            # ---- /api/config GET: populated + secret-free ----
            async with session.get(
                f"{base}/api/config", headers=bearer,
            ) as resp:
                assert resp.status == 200
                cfg_body = await resp.json()
            assert cfg_body["vault_path"] != ""
            assert "auth_token" not in cfg_body
            assert cfg_body["default_org"] == "alpha"

            # ---- /api/config PATCH: user_name write + comment preserved ----
            async with session.patch(
                f"{base}/api/config",
                headers=bearer,
                json={"user_name": "IntegrationTest"},
            ) as resp:
                assert resp.status == 200
                patch_body = await resp.json()
            assert patch_body["restart_required"] is True

            on_disk = config_path.read_text(encoding="utf-8")
            assert "IntegrationTest" in on_disk
            assert marker in on_disk

            # ---- config_updated journaled ----
            final_events = {
                e.get("event") for e in daemon.event_journal.tail(limit=200)
            }
            assert "config_updated" in final_events

    finally:
        await daemon.stop()
