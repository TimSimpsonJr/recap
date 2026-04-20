import { describe, it, expect } from "vitest";
import {
  deriveTodayMeetings,
  deriveUpcomingMeetings,
  derivePastMeetings,
  TabFilterState,
} from "./deriveMeetings";
import { MeetingData } from "../components/MeetingRow";

const NOW = new Date(2026, 3, 20, 14, 30); // 2026-04-20 14:30 local
const TODAY = "2026-04-20";

const DEFAULT_FILTER: TabFilterState = {
  org: "all",
  status: "all",
  company: "all",
  search: "",
};

function meeting(partial: Partial<MeetingData>): MeetingData {
  return {
    path: "Meetings/test.md",
    title: "",
    date: TODAY,
    time: "",
    org: "",
    duration: "",
    pipelineStatus: "pending",
    participants: [],
    companies: [],
    platform: "",
    ...partial,
  };
}

describe("deriveTodayMeetings", () => {
  it("returns empty rows and null divider for empty input", () => {
    const result = deriveTodayMeetings([], NOW, DEFAULT_FILTER);
    expect(result.rows).toEqual([]);
    expect(result.nowDividerIndex).toBeNull();
  });

  it("only keeps today's rows (filters yesterday and tomorrow)", () => {
    const rows = [
      meeting({ path: "y.md", date: "2026-04-19", time: "10:00-11:00" }),
      meeting({ path: "t.md", date: TODAY, time: "10:00-11:00" }),
      meeting({ path: "m.md", date: "2026-04-21", time: "10:00-11:00" }),
    ];
    const result = deriveTodayMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.rows.map(r => r.path)).toEqual(["t.md"]);
  });

  it("sorts ascending by start time", () => {
    const rows = [
      meeting({ path: "c.md", date: TODAY, time: "15:00-16:00" }),
      meeting({ path: "a.md", date: TODAY, time: "09:00-10:00" }),
      meeting({ path: "b.md", date: TODAY, time: "11:00-12:00" }),
    ];
    const result = deriveTodayMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.rows.map(r => r.path)).toEqual(["a.md", "b.md", "c.md"]);
  });

  it("marks isPast correctly for past, in-progress, and future rows", () => {
    const rows = [
      meeting({ path: "past.md", date: TODAY, time: "09:00-10:00" }),
      meeting({ path: "now.md", date: TODAY, time: "14:00-15:00" }),
      meeting({ path: "future.md", date: TODAY, time: "16:00-17:00" }),
    ];
    const result = deriveTodayMeetings(rows, NOW, DEFAULT_FILTER);
    const byPath = Object.fromEntries(result.rows.map(r => [r.path, r.isPast]));
    expect(byPath["past.md"]).toBe(true);
    expect(byPath["now.md"]).toBe(false);
    expect(byPath["future.md"]).toBe(false);
  });

  it("divider equals index of first non-past row when a mix exists", () => {
    const rows = [
      meeting({ path: "p1.md", date: TODAY, time: "08:00-09:00" }),
      meeting({ path: "p2.md", date: TODAY, time: "09:00-10:00" }),
      meeting({ path: "f1.md", date: TODAY, time: "15:00-16:00" }),
      meeting({ path: "f2.md", date: TODAY, time: "16:00-17:00" }),
    ];
    const result = deriveTodayMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.rows.map(r => r.path)).toEqual(["p1.md", "p2.md", "f1.md", "f2.md"]);
    expect(result.nowDividerIndex).toBe(2);
  });

  it("divider is null when all rows are past", () => {
    const rows = [
      meeting({ path: "a.md", date: TODAY, time: "08:00-09:00" }),
      meeting({ path: "b.md", date: TODAY, time: "10:00-11:00" }),
    ];
    const result = deriveTodayMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.nowDividerIndex).toBeNull();
  });

  it("divider is null when all rows are future/current", () => {
    const rows = [
      meeting({ path: "a.md", date: TODAY, time: "15:00-16:00" }),
      meeting({ path: "b.md", date: TODAY, time: "17:00-18:00" }),
    ];
    const result = deriveTodayMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.nowDividerIndex).toBeNull();
  });

  it("all-day rows sort to top and are never marked past", () => {
    const rows = [
      meeting({ path: "timed.md", date: TODAY, time: "09:00-10:00" }),
      meeting({ path: "allday.md", date: TODAY, time: "" }),
      meeting({ path: "later.md", date: TODAY, time: "16:00-17:00" }),
    ];
    const result = deriveTodayMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.rows[0].path).toBe("allday.md");
    expect(result.rows[0].isPast).toBe(false);
  });

  it("search filter is case-insensitive across title and participants", () => {
    const rows = [
      meeting({ path: "a.md", date: TODAY, time: "09:00-10:00", title: "Quarterly Planning" }),
      meeting({ path: "b.md", date: TODAY, time: "10:00-11:00", title: "Standup", participants: ["Alice Jones"] }),
      meeting({ path: "c.md", date: TODAY, time: "11:00-12:00", title: "Other" }),
    ];
    const titleResult = deriveTodayMeetings(rows, NOW, {
      ...DEFAULT_FILTER,
      search: "QUARTERLY",
    });
    expect(titleResult.rows.map(r => r.path)).toEqual(["a.md"]);

    const participantResult = deriveTodayMeetings(rows, NOW, {
      ...DEFAULT_FILTER,
      search: "alice",
    });
    expect(participantResult.rows.map(r => r.path)).toEqual(["b.md"]);
  });
});

describe("deriveUpcomingMeetings", () => {
  it("keeps date > today, ascending by date then start time", () => {
    const rows = [
      meeting({ path: "past.md", date: "2026-04-19", time: "09:00-10:00" }),
      meeting({ path: "today.md", date: TODAY, time: "09:00-10:00" }),
      meeting({ path: "tomlater.md", date: "2026-04-21", time: "15:00-16:00" }),
      meeting({ path: "tomearly.md", date: "2026-04-21", time: "09:00-10:00" }),
      meeting({ path: "future.md", date: "2026-04-25", time: "09:00-10:00" }),
    ];
    const result = deriveUpcomingMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.map(r => r.path)).toEqual(["tomearly.md", "tomlater.md", "future.md"]);
  });

  it("applies org filter", () => {
    const rows = [
      meeting({ path: "a.md", date: "2026-04-21", time: "09:00-10:00", org: "acme" }),
      meeting({ path: "b.md", date: "2026-04-21", time: "10:00-11:00", org: "other" }),
    ];
    const result = deriveUpcomingMeetings(rows, NOW, { ...DEFAULT_FILTER, org: "acme" });
    expect(result.map(r => r.path)).toEqual(["a.md"]);
  });
});

describe("derivePastMeetings", () => {
  it("keeps date < today, descending by date then start time", () => {
    const rows = [
      meeting({ path: "future.md", date: "2026-04-21", time: "09:00-10:00" }),
      meeting({ path: "today.md", date: TODAY, time: "09:00-10:00" }),
      meeting({ path: "yearly.md", date: "2026-04-19", time: "09:00-10:00" }),
      meeting({ path: "ylater.md", date: "2026-04-19", time: "15:00-16:00" }),
      meeting({ path: "older.md", date: "2026-04-15", time: "09:00-10:00" }),
    ];
    const result = derivePastMeetings(rows, NOW, DEFAULT_FILTER);
    expect(result.map(r => r.path)).toEqual(["ylater.md", "yearly.md", "older.md"]);
  });

  it("applies company filter, 'all' keeps everything", () => {
    const rows = [
      meeting({ path: "a.md", date: "2026-04-18", time: "09:00-10:00", companies: ["AcmeCo"] }),
      meeting({ path: "b.md", date: "2026-04-18", time: "10:00-11:00", companies: ["Other"] }),
      meeting({ path: "c.md", date: "2026-04-18", time: "11:00-12:00", companies: [] }),
    ];
    const all = derivePastMeetings(rows, NOW, { ...DEFAULT_FILTER, company: "all" });
    expect(all.length).toBe(3);

    const filtered = derivePastMeetings(rows, NOW, { ...DEFAULT_FILTER, company: "AcmeCo" });
    expect(filtered.map(r => r.path)).toEqual(["a.md"]);
  });

  it("applies status filter", () => {
    const rows = [
      meeting({ path: "a.md", date: "2026-04-18", time: "09:00-10:00", pipelineStatus: "complete" }),
      meeting({ path: "b.md", date: "2026-04-18", time: "10:00-11:00", pipelineStatus: "failed" }),
    ];
    const result = derivePastMeetings(rows, NOW, { ...DEFAULT_FILTER, status: "complete" });
    expect(result.map(r => r.path)).toEqual(["a.md"]);
  });
});
