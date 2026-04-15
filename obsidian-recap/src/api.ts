/**
 * HTTP + WebSocket client for communicating with the recap daemon.
 */
import { Notice } from "obsidian";

export class DaemonError extends Error {
    constructor(public status: number, message: string) {
        super(message);
        this.name = "DaemonError";
    }
}

export interface DaemonStatus {
    uptime_seconds: number;
    recent_errors: DaemonEvent[];
    // Legacy (kept for back-compat; mirror new fields):
    state: "idle" | "armed" | "detected" | "recording" | "processing";
    recording: { path: string; org: string } | null;
    daemon_uptime: number;
    last_calendar_sync: string | null;
    errors: DaemonEvent[];
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
            throw new DaemonError(resp.status, await resp.text());
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
            throw new DaemonError(resp.status, await resp.text());
        }
        return resp.json() as Promise<T>;
    }

    async delete(path: string): Promise<void> {
        const resp = await fetch(`${this.baseUrl}${path}`, {
            method: "DELETE",
            headers: { "Authorization": `Bearer ${this.token}` },
        });
        if (!resp.ok) {
            throw new DaemonError(resp.status, await resp.text());
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

    async startRecording(org: string): Promise<{ recording_path: string }> {
        return this.post("/api/record/start", { org });
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

    async submitSpeakerCorrections(recordingPath: string, mapping: Record<string, string>, org: string): Promise<void> {
        await this.post("/api/meetings/speakers", {
            recording_path: recordingPath,
            mapping,
            org,
        });
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
            throw new DaemonError(resp.status, await resp.text());
        }
        return resp.json() as Promise<PatchConfigResponse>;
    }
}
