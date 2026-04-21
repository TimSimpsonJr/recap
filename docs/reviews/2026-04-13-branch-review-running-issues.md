# Branch Review Running Issues

This file tracks issues found during the phase-by-phase review of the `obsidian-pivot` branch.

Scope notes:
- Reviews are done at each phase endpoint commit, not against final `HEAD`.
- Later phases are ignored unless they affect whether an earlier phase was coherent on its own.
- This list is intended to be handed to Claude for fixes after review is complete.

## Running Issues

1. Phase 0: `recap/pipeline.py` still imports and uses deleted modules (`frames`, `todoist`, `transcribe`) at the Phase 0 endpoint, so the cleanup phase leaves the repo in a non-importable state.

2. Phase 0: `recap/cli.py` still exposes Todoist-related commands after `recap/todoist.py` was removed, leaving dead CLI paths in the cleanup snapshot.

3. Phase 1: the GPU startup check always warns falsely in a Phase 1 install because `validate_startup()` depends on importing `torch`, but the Phase 1 dependency set does not include `torch`.

4. Phase 1: startup validation is missing the promised model-cache check, so pipeline readiness is overstated even though the phase plan explicitly called for a non-fatal models check.

5. Phase 2: the recorder never returns from `processing` to `idle` after a normal stop, so only the first manual recording works cleanly before later phases patch around it.

6. Phase 2: orphan recovery misclassifies all normal Phase 2 FLAC files as incomplete because it expects pipeline status files that do not exist yet at the Phase 2 endpoint.

7. Phase 3: the speaker-correction reprocess flow is nonfunctional because `/api/meetings/speakers` triggers an export-only rerun, but the pipeline never reconstructs `analysis` or consumes the saved speaker mapping file.

8. Phase 3: pipeline status writing and orphan recovery still use incompatible file locations and naming, so completed recordings continue to look orphaned on restart.

9. Phase 4: daemon startup is broken at the Phase 4 endpoint because `__main__.py` passes `detector=detector` into `create_app(...)`, but `server.create_app()` does not accept a `detector` parameter in that snapshot.

10. Phase 4: auto-record detection is nonfunctional because `MeetingDetector._poll_once()` calls the async `recorder.start(org)` method without awaiting or scheduling it, so detected meetings do not actually start recording.

11. Phase 4: browser extension listener endpoints acknowledge `/meeting-detected` and `/meeting-ended`, but they are not wired into the detector or recorder logic, so extension signals do not influence detection behavior despite the phase plan requiring that integration.

12. Phase 5: the OAuth start endpoint returns an authorization URL with `http://localhost:0/callback` because it calls `OAuthManager.get_authorization_url()` before the temporary callback server has started and resolved its ephemeral port. That makes the Phase 5 browser auth flow invalid at the moment it is initiated.

13. Phase 5: Zoho calendar sync is effectively unreachable because the scheduler requires a stored `calendar_id` for non-Google providers, but the Phase 5 OAuth and config paths never persist or supply a Zoho calendar ID anywhere. Google gets a `"primary"` fallback; Zoho just returns no events.

14. Phase 5: unchanged events with participants are treated as changed on the first resync because notes are initially written with participant wikilinks like `[[Alice]]`, but update detection compares those stored values against raw participant names and `update_calendar_note()` rewrites the field back to plain strings. That creates unnecessary churn and drifts the note schema away from the format Phase 5 originally wrote.

15. Phase 6: the plugin does not build at the Phase 6 endpoint because `obsidian-recap/src/main.ts` imports `./views/MeetingListView`, registers that view, and exposes dashboard entry points, but `obsidian-recap/src/views/MeetingListView.ts` is not present in the `9ea1801` tree at all.

16. Phase 6: changing the daemon URL in plugin settings does not actually reconfigure the plugin session. The settings tab only saves the new string, while `DaemonClient` is instantiated once during `onload()` and all commands, OAuth actions, and status checks continue using the old client until the plugin is reloaded.

17. Phase 6: the status bar can get stuck showing `Daemon offline` after a temporary disconnect. The plugin marks offline on WebSocket close, but there is no `onopen` handler or reconnect status refresh to clear that state when the socket comes back unless a later `state_change` event happens to arrive.

18. Phase 7: file rename processing is nonfunctional end-to-end. The plugin expects `_Recap/.recap/rename-queue.json` to contain an array of rename entries, but the daemon-side writer still emits a single JSON object when a date change is detected, and the calendar scheduler never actually passes a `rename_queue_path` into `update_calendar_note()` anyway. As implemented at the Phase 7 endpoint, there is no working path that produces consumable rename jobs for the plugin.

19. Phase 7: notification history is effectively dead because the plugin records entries only for `error`, `processing_complete`, `recording_started`, and `recording_stopped` WebSocket events, while the daemon snapshot only broadcasts `state_change`. The notification modal therefore stays empty in normal use despite the feature appearing to be wired up.

20. Phase 7: the live transcript view shows a false idle state if the user opens it while a recording is already in progress. `LiveTranscriptView.onOpen()` hardcodes `updateStatus("idle")`, and the plugin only updates the view on future `state_change` events, so opening the pane mid-recording does not reflect the actual daemon state until another transition happens.

21. Phase 8: the live transcript pane still never renders streaming text because the daemon now broadcasts `transcript_segment` events, but the plugin only listens for `state_change`, notification events, and `rename_queued`. `LiveTranscriptView.appendUtterance()` exists, yet nothing ever calls it at the Phase 8 endpoint.

22. Phase 8: the streaming models only receive microphone audio, not the full meeting audio. The recorder patches the audio drain loop to snapshot `capture._mic_buffer` and feeds that mono mic buffer into both the transcriber and diarizer, while ignoring the loopback/system-audio buffer. In practice, that means remote participants on Teams/Zoom/Meet are absent from the real-time transcript path.

23. Phase 8: the streaming diarizer is still a stub. `StreamingDiarizer._process_audio()` contains only placeholder comments and never emits speaker segments, so Phase 8 does not actually provide real-time diarization. Because the pipeline only skips batch work when the streaming transcript already has real speaker labels, this stubbed diarizer also prevents the “skip transcribe/diarize when streaming succeeded” path from being reliably realized.

24. Phase 9: the Windows auto-start toggle is not implemented. The branch adds only a stub `recap.daemon.autostart` module and a read-only `GET /api/autostart` status endpoint that always reports `implemented: false`; the enable/disable endpoints from the Phase 9 plan do not exist, and the helper functions intentionally return failure.

## Deferred Phase 9 Items

- PyInstaller packaging: not implemented; continue running via `python -m recap.daemon` for now.
- Claude Desktop scheduled task prompts: briefing + note enrichment prompts were deferred.
- Windows Task Scheduler auto-start: stub in place, but actual registration/removal is deferred.
- End-to-end manual testing: deferred.
