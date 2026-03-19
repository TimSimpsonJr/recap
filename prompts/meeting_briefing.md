You are preparing a pre-meeting briefing. Given notes from past meetings with the same company or participants, produce a structured JSON prep brief.

## Upcoming Meeting

Title: {{title}}
Participants: {{participants}}
Time: {{time}}

## Past Meeting Notes

{{past_notes}}

## Instructions

Produce a JSON object with exactly these fields:

1. **topics** — array of strings: ongoing discussion threads and recurring themes across past meetings. Focus on what's still active or unresolved.

2. **action_items** — array of {assignee, description, from_meeting} objects: open items attributed to upcoming meeting attendees. from_meeting is the meeting title where the item was assigned.

3. **context** — string: meeting frequency, how long you've been meeting with these people, any notable patterns.

4. **relationship_summary** — string: working relationship dynamics, communication style, what this person or group cares about most.

5. **first_meeting** — boolean: true if no past meeting notes were provided.

Keep each field concise. Use bullet points within strings, not paragraphs. Focus on what's actionable for the upcoming meeting.

Output ONLY valid JSON. No markdown fences, no explanation, no preamble.
