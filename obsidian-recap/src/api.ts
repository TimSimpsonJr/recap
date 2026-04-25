/**
 * HTTP + WebSocket client for communicating with the recap daemon.
 */
import { Notice } from "obsidian";

export class DaemonError extends Error {
    constructor(
        public status: number,
        message: string,
        public body?: unknown,  // parsed JSON body when available
    ) {
        super(message);
        this.name = "DaemonError";
    }
}

export interface DaemonStatus {
    state: "idle" | "armed" | "detected" | "recording" | "processing";
    recording: { path: string; org: string } | null;
    last_calendar_sync: string | null;
    uptime_seconds: number;
    recent_errors: DaemonEvent[];
    // Launcher-wrapper mode: true when the daemon was spawned by
    // ``recap.launcher`` (env ``RECAP_MANAGED=1``). Older daemon
    // versions don't send these fields, so treat absent as false.
    managed?: boolean;
    can_restart?: boolean;
}

export interface JournalEntry {
    ts: string;
    level: "info" | "warning" | "error";
    event: string;
    message: string;
    payload?: Record<string, unknown>;
}

export interface DaemonEvent {
    event: string;
    [key: string]: unknown;
}

export interface ApiOrg {
    name: string;
    subfolder: string;
    default: boolean;
}

export interface ApiDetectionRule {
    enabled: boolean;
    behavior: "auto-record" | "prompt";
    default_org: string | null;
    default_backend: string | null;
}

export interface ApiCalendarProvider {
    enabled: boolean;
    calendar_id: string | null;
    org: string | null;
}

export interface ApiKnownContact {
    name: string;
    aliases: string[];
    email: string | null;
    // ``display_name`` is what the speaker-matching pipeline keys off,
    // so the UI must round-trip it to avoid destroying existing
    // matching rules. Null = preserve on-disk value (new contacts
    // default to ``name`` server-side).
    display_name: string | null;
}

export interface ApiConfigDto {
    vault_path: string;
    recordings_path: string;
    user_name: string | null;
    plugin_port: number;
    orgs: ApiOrg[];
    default_org: string | null;
    detection: Record<string, ApiDetectionRule>;
    calendar: Record<string, ApiCalendarProvider>;
    known_contacts: ApiKnownContact[];
    recording_silence_timeout_minutes: number;
    recording_max_duration_hours: number;
    logging_retention_days: number;
}

export interface PatchConfigResponse {
    status: string;
    restart_required: boolean;
}

// Atomic contact mutations sent alongside a speaker-correction save.
// ``create`` minted a brand-new known_contacts entry (and, server-side,
// a People note stub); ``add_alias`` folded a typed name onto an
// existing canonical contact. See design doc Section 4.5.
export type ContactMutation =
    | {action: "create"; name: string; display_name: string; email?: string}
    | {action: "add_alias"; name: string; alias: string};

export class DaemonClient {
    private baseUrl: string;
    private token: string;
    private ws: WebSocket | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private eventHandlers: Map<string, ((event: DaemonEvent) => void)[]> = new Map();

    constructor(baseUrl: string, token: string) {
        this.baseUrl = baseUrl;
        this.token = token;
    }

    // --- HTTP methods ---

    async get<T>(path: string): Promise<T> {
        const resp = await fetch(`${this.baseUrl}${path}`, {
            headers: { "Authorization": `Bearer ${this.token}` },
        });
        if (!resp.ok) {
            const text = await resp.text();
            let parsed: unknown;
            try { parsed = JSON.parse(text); } catch {}
            throw new DaemonError(resp.status, text, parsed);
        }
        return resp.json() as Promise<T>;
    }

    async post<T>(path: string, body?: unknown): Promise<T> {
        const resp = await fetch(`${this.baseUrl}${path}`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${this.token}`,
                "Content-Type": "application/json",
            },
            body: body ? JSON.stringify(body) : undefined,
        });
        if (!resp.ok) {
            const text = await resp.text();
            let parsed: unknown;
            try { parsed = JSON.parse(text); } catch {}
            throw new DaemonError(resp.status, text, parsed);
        }
        return resp.json() as Promise<T>;
    }

    async delete(path: string): Promise<void> {
        const resp = await fetch(`${this.baseUrl}${path}`, {
            method: "DELETE",
            headers: { "Authorization": `Bearer ${this.token}` },
        });
        if (!resp.ok) {
            const text = await resp.text();
            let parsed: unknown;
            try { parsed = JSON.parse(text); } catch {}
            throw new DaemonError(resp.status, text, parsed);
        }
    }

    // --- WebSocket ---

    connectWebSocket(onDisconnect?: () => void): void {
        if (this.ws) return;

        const wsUrl = this.baseUrl.replace(/^https?/, (m) => m === "https" ? "wss" : "ws")
            + `/api/ws?token=${encodeURIComponent(this.token)}`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            const handlers = this.eventHandlers.get("_connected") || [];
            handlers.forEach(h => h({ event: "_connected" }));
        };

        this.ws.onmessage = (event: MessageEvent) => {
            try {
                const data: DaemonEvent = JSON.parse(event.data as string);
                const handlers = this.eventHandlers.get(data.event) || [];
                handlers.forEach(h => h(data));
                // Also fire wildcard handlers
                const wildcardHandlers = this.eventHandlers.get("*") || [];
                wildcardHandlers.forEach(h => h(data));
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(`Recap: malformed WebSocket message \u2014 ${msg}`);
                console.error("Recap:", e);
            }
        };

        this.ws.onclose = () => {
            this.ws = null;
            onDisconnect?.();
            // Auto-reconnect after 10 seconds
            this.reconnectTimer = setTimeout(() => {
                this.connectWebSocket(onDisconnect);
            }, 10000);
        };

        this.ws.onerror = (error: Event) => {
            console.error("WebSocket error:", error);
        };
    }

    disconnectWebSocket(): void {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    on(event: string, handler: (data: DaemonEvent) => void): () => void {
        const handlers = this.eventHandlers.get(event) || [];
        handlers.push(handler);
        this.eventHandlers.set(event, handlers);
        return () => {
            const current = this.eventHandlers.get(event);
            if (!current) return;
            const idx = current.indexOf(handler);
            if (idx !== -1) {
                current.splice(idx, 1);
            }
        };
    }

    off(event: string, handler: (data: DaemonEvent) => void): void {
        const handlers = this.eventHandlers.get(event) || [];
        this.eventHandlers.set(event, handlers.filter(h => h !== handler));
    }

    get isConnected(): boolean {
        return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
    }

    // --- Convenience methods ---

    async getStatus(): Promise<DaemonStatus> {
        return this.get<DaemonStatus>("/api/status");
    }

    async startRecording(
        org: string,
        backend?: string,
    ): Promise<{ recording_path: string }> {
        // ``backend`` is optional so older callers still work; when
        // supplied it's one of the strings returned by
        // ``/api/config/orgs``'s ``backends`` list (e.g. "claude",
        // "ollama") and flows into ``RecordingMetadata.llm_backend``.
        const body: Record<string, string> = { org };
        if (backend) body.backend = backend;
        return this.post("/api/record/start", body);
    }

    async stopRecording(): Promise<{ recording_path: string }> {
        return this.post("/api/record/stop");
    }

    async reprocess(recordingPath: string, fromStage?: string, org?: string): Promise<void> {
        await this.post("/api/meetings/reprocess", {
            recording_path: recordingPath,
            from_stage: fromStage,
            org,
        });
    }

    /** Fetch the transcript's distinct ``(speaker_id, display)`` pairs
     * along with the recording's metadata ``participants`` (names +
     * optional emails from calendar-sourced entries). Drives the
     * #28 speaker-correction modal's resolution engine. */
    async getMeetingSpeakers(stem: string): Promise<{
        speakers: Array<{speaker_id: string; display: string}>;
        participants: Array<{name: string; email: string | null}>;
    }> {
        return this.get(
            `/api/meetings/${encodeURIComponent(stem)}/speakers`,
        );
    }

    /** Save a #28-style speaker correction: ``mapping`` keyed by
     * ``speaker_id`` + atomic ``contact_mutations`` the daemon applies
     * before reprocess. Supersedes the pre-#28 ``recording_path``-keyed
     * submit, which has been removed — the daemon still accepts that
     * shape on the wire for back-compat but no plugin code emits it. */
    async saveSpeakerCorrections(params: {
        stem: string;
        mapping: Record<string, string>;
        contact_mutations: ContactMutation[];
        org: string;
    }): Promise<{status: string}> {
        return this.post("/api/meetings/speakers", params);
    }

    async getOAuthStatus(provider: string): Promise<{ connected: boolean; provider: string }> {
        return this.get(`/api/oauth/${provider}/status`);
    }

    async startOAuth(provider: string): Promise<{ authorize_url: string }> {
        return this.post(`/api/oauth/${provider}/start`);
    }

    async disconnectOAuth(provider: string): Promise<void> {
        await this.delete(`/api/oauth/${provider}`);
    }

    async arm(eventId: string, startTime: string, org: string): Promise<void> {
        await this.post("/api/arm", { event_id: eventId, start_time: startTime, org });
    }

    async disarm(): Promise<void> {
        await this.post("/api/disarm");
    }

    /**
     * Ask the daemon to shut down. ``restart: true`` is only honored
     * when the daemon was launched via ``recap.launcher`` (returns 409
     * otherwise). The daemon sends the 200 before tearing down, so the
     * caller should poll ``/api/status`` to observe the replacement
     * process coming online.
     */
    async requestShutdown(restart: boolean): Promise<void> {
        await this.post("/api/admin/shutdown", { restart });
    }

    async tailEvents(since?: string, limit?: number): Promise<JournalEntry[]> {
        const params = new URLSearchParams();
        if (since !== undefined) params.set("since", since);
        if (limit !== undefined) params.set("limit", String(limit));
        const query = params.toString();
        const path = query ? `/api/events?${query}` : "/api/events";
        const resp = await this.get<{ entries: JournalEntry[] }>(path);
        return resp.entries;
    }

    onJournalEntry(handler: (entry: JournalEntry) => void): () => void {
        const dispatch = (event: DaemonEvent) => {
            const entry = (event as { entry?: JournalEntry }).entry;
            if (entry) handler(entry);
        };
        return this.on("journal_entry", dispatch);
    }

    async getConfig(): Promise<ApiConfigDto> {
        return this.get<ApiConfigDto>("/api/config");
    }

    /** URL for streaming. Not used for auth'd fetches (tokens must not
     * land in query strings that could leak through referrers or logs);
     * see ``fetchSpeakerClip`` for the Bearer-authed variant.
     *
     * Query key is ``speaker_id`` as of #28 — the daemon still accepts
     * ``speaker`` as a fallback during the transition (Task 9), but
     * the plugin always sends the stable diarized identity so clip
     * cache entries survive display relabels. */
    getSpeakerClipUrl(
        stem: string, speakerId: string, duration = 5,
    ): string {
        const params = new URLSearchParams({
            speaker_id: speakerId, duration: String(duration),
        });
        return `${this.baseUrl}/api/recordings/${
            encodeURIComponent(stem)
        }/clip?${params.toString()}`;
    }

    async fetchSpeakerClip(
        stem: string, speakerId: string, duration = 5,
    ): Promise<Blob> {
        const resp = await fetch(
            this.getSpeakerClipUrl(stem, speakerId, duration),
            {
                headers: { "Authorization": `Bearer ${this.token}` },
            },
        );
        if (!resp.ok) {
            const text = await resp.text();
            let parsed: unknown;
            try { parsed = JSON.parse(text); } catch {}
            throw new DaemonError(resp.status, text, parsed);
        }
        return resp.blob();
    }

    async patchConfig(
        patch: Partial<ApiConfigDto>,
    ): Promise<PatchConfigResponse> {
        const resp = await fetch(`${this.baseUrl}/api/config`, {
            method: "PATCH",
            headers: {
                "Authorization": `Bearer ${this.token}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify(patch),
        });
        if (!resp.ok) {
            const text = await resp.text();
            let parsed: unknown;
            try { parsed = JSON.parse(text); } catch {}
            throw new DaemonError(resp.status, text, parsed);
        }
        return resp.json() as Promise<PatchConfigResponse>;
    }
}
