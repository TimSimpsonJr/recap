import { MeetingData } from "../components/MeetingRow";
import { parseMeetingTime, todayIsoDate } from "./meetingTime";

export type Tab = "today" | "upcoming" | "past";

export interface TabFilterState {
  org: string;
  status: string;
  company: string;
  search: string;
}

export interface DecoratedRow extends MeetingData {
  isPast: boolean;
}

export interface TodayDeriveResult {
  rows: DecoratedRow[];
  nowDividerIndex: number | null;
}

function minutesSinceMidnight(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function isRowPast(m: MeetingData, now: Date): boolean {
  const parsed = parseMeetingTime(m.time);
  if (parsed.allDay) return false;
  const nowMin = now.getHours() * 60 + now.getMinutes();
  return minutesSinceMidnight(parsed.end) < nowMin;
}

function matchesOrg(m: MeetingData, filter: TabFilterState): boolean {
  return filter.org === "all" || m.org === filter.org;
}

function matchesCompany(m: MeetingData, filter: TabFilterState): boolean {
  if (filter.company === "all") return true;
  return m.companies.includes(filter.company);
}

function matchesStatus(m: MeetingData, filter: TabFilterState): boolean {
  if (filter.status === "all") return true;
  if (filter.status === "failed") return m.pipelineStatus.startsWith("failed");
  return m.pipelineStatus === filter.status;
}

function matchesSearch(m: MeetingData, filter: TabFilterState): boolean {
  if (!filter.search) return true;
  const q = filter.search.toLowerCase();
  if (m.title.toLowerCase().includes(q)) return true;
  return m.participants.some(p => p.toLowerCase().includes(q));
}

function passesAllFilters(m: MeetingData, filter: TabFilterState): boolean {
  return (
    matchesOrg(m, filter) &&
    matchesCompany(m, filter) &&
    matchesStatus(m, filter) &&
    matchesSearch(m, filter)
  );
}

function decorate(m: MeetingData, now: Date): DecoratedRow {
  return { ...m, isPast: isRowPast(m, now) };
}

export function deriveTodayMeetings(
  meetings: MeetingData[],
  now: Date,
  filter: TabFilterState,
): TodayDeriveResult {
  const today = todayIsoDate(now);
  const rows = meetings
    .filter(m => m.date === today)
    .filter(m => passesAllFilters(m, filter))
    .map(m => decorate(m, now))
    .sort(
      (a, b) =>
        minutesSinceMidnight(parseMeetingTime(a.time).start) -
        minutesSinceMidnight(parseMeetingTime(b.time).start),
    );

  const firstNonPast = rows.findIndex(r => !r.isPast);
  const hasPast = rows.some(r => r.isPast);
  const nowDividerIndex =
    firstNonPast > 0 && hasPast ? firstNonPast : null;

  return { rows, nowDividerIndex };
}

export function deriveUpcomingMeetings(
  meetings: MeetingData[],
  now: Date,
  filter: TabFilterState,
): DecoratedRow[] {
  const today = todayIsoDate(now);
  return meetings
    .filter(m => m.date > today)
    .filter(m => passesAllFilters(m, filter))
    .map(m => decorate(m, now))
    .sort((a, b) => {
      if (a.date !== b.date) return a.date.localeCompare(b.date);
      return (
        minutesSinceMidnight(parseMeetingTime(a.time).start) -
        minutesSinceMidnight(parseMeetingTime(b.time).start)
      );
    });
}

export function derivePastMeetings(
  meetings: MeetingData[],
  now: Date,
  filter: TabFilterState,
): DecoratedRow[] {
  const today = todayIsoDate(now);
  return meetings
    .filter(m => m.date < today)
    .filter(m => passesAllFilters(m, filter))
    .map(m => decorate(m, now))
    .sort((a, b) => {
      if (a.date !== b.date) return b.date.localeCompare(a.date);
      return (
        minutesSinceMidnight(parseMeetingTime(b.time).start) -
        minutesSinceMidnight(parseMeetingTime(a.time).start)
      );
    });
}
