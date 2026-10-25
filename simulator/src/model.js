export const scenes = {
  limits: {
    mode: "models",
    accent: "#d9ff3f",
    providers: [
      { id: "codex", name: "ChatGPT", color: "#44c7f4", remaining: 72, window: "5H", reset: [2, 14], secondaryLabel: "WEEK", secondary: 43 },
      { id: "claude", name: "Claude", color: "#ff6b1a", remaining: 48, window: "5H", reset: [0, 48], secondaryLabel: "WEEK", secondary: 67 },
    ],
    synced: "30 SEC AGO",
    weather: { location: "MOSCOW", temperature: 18, condition: "CLOUDY", high: 20, low: 12 },
  },
  focus: { accent: "#d9ff3f", presenceTitle: "FOCUS", presenceNote: "UNTIL 16:45", primaryLabel: "NOW", primaryTitle: "UI PROTOTYPE", primaryNote: "AMBIENT STATUS BAR", progressLabel: "SESSION", progress: 62, progressTitle: "37 MIN", progressNote: "23 LEFT" },
  call: { accent: "#ff7356", presenceTitle: "ON CALL", presenceNote: "DO NOT DISTURB", primaryLabel: "MEETING", primaryTitle: "PRODUCT SYNC", primaryNote: "ANNA / MARK / LEO", progressLabel: "LIVE", progress: 34, progressTitle: "18 MIN", progressNote: "TO 17:00" },
  build: { accent: "#68d8ff", presenceTitle: "BUILDING", presenceNote: "BRANCH MAIN", primaryLabel: "CODEX", primaryTitle: "FIRMWARE UI", primaryNote: "CHECKING COMPONENTS", progressLabel: "TASKS", progress: 78, progressTitle: "7 OF 9", progressNote: "2 LEFT" },
};

export const cells = {
  limits: ["Model limits", "Codex and Claude side by side; the layout fits up to four models."],
  codex: ["Codex", "Remaining share of the current window, weekly limit and reset time."],
  claude: ["Claude", "Remaining share of the current window, weekly limit and reset time."],
  weather: ["Time and weather", "Local time, date, temperature and a short forecast."],
  presence: ["Presence", "A quick signal of availability and the current mode."],
  primary: ["Main context", "The central cell gets the most space."],
  progress: ["Progress", "A timer, task or process with a clear end point."],
  time: ["Time and link", "A stable anchor cell with system status."],
};

export const layout = { width: 960, height: 240, columns: [0, 190, 520, 760, 960], padding: 28 };
