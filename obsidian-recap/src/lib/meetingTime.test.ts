import { describe, it, expect } from "vitest";
import { parseMeetingTime, todayIsoDate, isSameLocalDay } from "./meetingTime";

describe("parseMeetingTime", () => {
  it("parses a well-formed HH:MM-HH:MM range", () => {
    expect(parseMeetingTime("14:00-15:00")).toEqual({
      start: "14:00",
      end: "15:00",
      allDay: false,
    });
  });

  it("returns the all-day sentinel for undefined, empty, garbage, or partial inputs", () => {
    const sentinel = { start: "00:00", end: "23:59", allDay: true };
    expect(parseMeetingTime(undefined)).toEqual(sentinel);
    expect(parseMeetingTime("")).toEqual(sentinel);
    expect(parseMeetingTime("garbage")).toEqual(sentinel);
    expect(parseMeetingTime("14:00")).toEqual(sentinel);
  });

  it("returns the all-day sentinel when hour is out of range", () => {
    const sentinel = { start: "00:00", end: "23:59", allDay: true };
    expect(parseMeetingTime("25:00-26:00")).toEqual(sentinel);
  });

  it("returns the all-day sentinel when minute is out of range", () => {
    const sentinel = { start: "00:00", end: "23:59", allDay: true };
    expect(parseMeetingTime("14:60-15:70")).toEqual(sentinel);
  });

  it("parses a valid range with non-zero minutes", () => {
    expect(parseMeetingTime("09:30-10:45")).toEqual({
      start: "09:30",
      end: "10:45",
      allDay: false,
    });
  });
});

describe("todayIsoDate", () => {
  it("formats a mid-afternoon local date as YYYY-MM-DD with zero-padding", () => {
    expect(todayIsoDate(new Date(2026, 3, 20, 14, 30))).toBe("2026-04-20");
  });

  it("does not flip a late-evening local date to UTC's next day", () => {
    expect(todayIsoDate(new Date(2026, 3, 20, 22, 0))).toBe("2026-04-20");
  });
});

describe("isSameLocalDay", () => {
  it("returns true for two Dates within the same local day", () => {
    const a = new Date(2026, 3, 20, 8, 15);
    const b = new Date(2026, 3, 20, 23, 45);
    expect(isSameLocalDay(a, b)).toBe(true);
  });

  it("returns false across a local-midnight boundary", () => {
    const a = new Date(2026, 3, 20, 23, 59);
    const b = new Date(2026, 3, 21, 0, 1);
    expect(isSameLocalDay(a, b)).toBe(false);
  });
});
