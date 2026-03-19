const DEFAULT_PATTERNS = [
  { pattern: "meet.google.com/", platform: "google_meet" },
  { pattern: "teams.microsoft.com/", platform: "teams", requirePath: ["meetup-join", "pre-join"] },
  { pattern: "meeting.zoho.com/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.eu/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.in/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.com.au/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.tranzpay.io/", platform: "zoho_meet" },
];

const PLATFORMS = ["google_meet", "teams", "zoho_meet", "unknown"];

const container = document.getElementById("patterns");
const addBtn = document.getElementById("add-btn");
const saveBtn = document.getElementById("save-btn");
const resetBtn = document.getElementById("reset-btn");
const savedMsg = document.getElementById("saved-msg");

function createPatternRow(pattern, index) {
  const row = document.createElement("div");
  row.className = "pattern-row";
  row.dataset.index = index;

  const input = document.createElement("input");
  input.type = "text";
  input.value = pattern.pattern;
  input.placeholder = "e.g. meet.google.com/";
  row.appendChild(input);

  const select = document.createElement("select");
  for (const p of PLATFORMS) {
    const option = document.createElement("option");
    option.value = p;
    option.textContent = p;
    if (p === pattern.platform) option.selected = true;
    select.appendChild(option);
  }
  row.appendChild(select);

  const removeBtn = document.createElement("button");
  removeBtn.className = "remove-btn";
  removeBtn.textContent = "\u00d7";
  removeBtn.title = "Remove pattern";
  row.appendChild(removeBtn);

  return row;
}

function renderPatterns(patterns) {
  const rows = patterns.map((p, i) => createPatternRow(p, i));
  container.replaceChildren(...rows);
}

function collectPatterns() {
  const rows = container.querySelectorAll(".pattern-row");
  const patterns = [];
  for (const row of rows) {
    const input = row.querySelector("input");
    const select = row.querySelector("select");
    const value = input.value.trim();
    if (value) {
      patterns.push({ pattern: value, platform: select.value });
    }
  }
  return patterns;
}

async function load() {
  const result = await chrome.storage.local.get("meetingPatterns");
  const patterns = result.meetingPatterns || DEFAULT_PATTERNS;
  renderPatterns(patterns);
}

function showSaved() {
  savedMsg.classList.add("visible");
  setTimeout(() => savedMsg.classList.remove("visible"), 2000);
}

saveBtn.addEventListener("click", async () => {
  const patterns = collectPatterns();
  await chrome.storage.local.set({ meetingPatterns: patterns });
  showSaved();
});

resetBtn.addEventListener("click", () => {
  renderPatterns(DEFAULT_PATTERNS);
});

addBtn.addEventListener("click", () => {
  const row = createPatternRow({ pattern: "", platform: "unknown" }, container.children.length);
  container.appendChild(row);
});

container.addEventListener("click", (e) => {
  if (e.target.classList.contains("remove-btn")) {
    e.target.closest(".pattern-row").remove();
  }
});

load();
