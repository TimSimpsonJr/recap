export interface ParsedMeetingTime {
  start: string;
  end: string;
  allDay: boolean;
}

const ALL_DAY: ParsedMeetingTime = {
  start: "00:00",
  end: "23:59",
  allDay: true,
};

const TIME_RANGE = /^(\d{2}):(\d{2})-(\d{2}):(\d{2})$/;

export function parseMeetingTime(
  raw: string | undefined | null,
): ParsedMeetingTime {
  if (raw == null) {
    return ALL_DAY;
  }
  const trimmed = raw.trim();
  const match = TIME_RANGE.exec(trimmed);
  if (!match) {
    return ALL_DAY;
  }
  return {
    start: `${match[1]}:${match[2]}`,
    end: `${match[3]}:${match[4]}`,
    allDay: false,
  };
}

export function todayIsoDate(now: Date = new Date()): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isSameLocalDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}
