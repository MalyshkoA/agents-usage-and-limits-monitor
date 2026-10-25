import { layout } from "./model.js";

const FONT = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const TEXT = "#f4f6f2";
const MUTED = "#7c858d";
const LINE = "#191d20";

function text(ctx, value, x, y, size, color, weight = 500, align = "left") {
  ctx.fillStyle = color;
  ctx.font = `${weight} ${size}px ${FONT}`;
  ctx.textAlign = align;
  ctx.textBaseline = "alphabetic";
  ctx.fillText(value, x, y);
}

function label(ctx, value, x, y, color = MUTED) { text(ctx, value, x, y, 11, color, 700); }

function roundRect(ctx, x, y, width, height, radius, fill) {
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, radius);
  ctx.fillStyle = fill;
  ctx.fill();
}

function selection(ctx, x, width, color) {
  ctx.fillStyle = `${color}0a`;
  ctx.fillRect(x + 1, 1, width - 2, 238);
  ctx.strokeStyle = `${color}73`;
  ctx.strokeRect(x + 0.5, 0.5, width - 1, 239);
}

function drawGrid(ctx) {
  ctx.strokeStyle = "rgba(255,255,255,.13)";
  for (let x = 0; x <= 960; x += 24) { ctx.beginPath(); ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, 240); ctx.stroke(); }
  for (let y = 0; y <= 240; y += 24) { ctx.beginPath(); ctx.moveTo(0, y + .5); ctx.lineTo(960, y + .5); ctx.stroke(); }
}

function drawProviderMark(ctx, provider, cx, cy, scale = 1) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(scale, scale);
  ctx.strokeStyle = provider.color;
  ctx.fillStyle = provider.color;
  ctx.lineCap = "round";
  if (provider.id === "codex") {
    ctx.lineWidth = 3.2;
    for (let i = 0; i < 6; i += 1) {
      ctx.save();
      ctx.rotate(i * Math.PI / 3);
      ctx.beginPath();
      ctx.roundRect(1, -4.2, 12, 8.4, 4.2);
      ctx.stroke();
      ctx.restore();
    }
    ctx.beginPath(); ctx.arc(0, 0, 4.2, 0, Math.PI * 2); ctx.fillStyle = "#020304"; ctx.fill();
  } else {
    ctx.lineWidth = 3.6;
    for (let i = 0; i < 6; i += 1) {
      ctx.beginPath();
      ctx.moveTo(Math.cos(i * Math.PI / 3) * 3, Math.sin(i * Math.PI / 3) * 3);
      ctx.lineTo(Math.cos(i * Math.PI / 3) * 13, Math.sin(i * Math.PI / 3) * 13);
      ctx.stroke();
    }
  }
  ctx.restore();
}

// Limits scene uses the Spleen pixel font at native sizes, same as device/code.py.
// Coordinates mirror the device: y is the vertical centre of the text line.
const UTILITY_WIDTH = 220;
const PIXEL = { label: '24px "Spleen 12x24"', value: '32px "Spleen 16x32"', hero: '64px "Spleen 32x64"', timer: '48px "Spleen 32x64"' };

function pixelText(ctx, value, x, y, font = PIXEL.label, color = MUTED, align = "left", baseline = "middle") {
  ctx.fillStyle = color;
  ctx.font = font;
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  ctx.fillText(value, x, y);
}

// Time to the 5h reset, right-aligned on the percentage baseline (same as device):
// "1 h 25 min" / "25 min" with large numbers and muted units.
const HERO_BASELINE = 114;
function drawReset(ctx, [hours, minutes], right) {
  const parts = hours
    ? [[String(hours), PIXEL.timer, TEXT, 0], ["h", PIXEL.label, MUTED, 5], [String(minutes), PIXEL.timer, TEXT, 12], ["min", PIXEL.label, MUTED, 5]]
    : [[String(minutes), PIXEL.timer, TEXT, 0], ["min", PIXEL.label, MUTED, 5]];
  let x = right;
  for (const [value, font, color, gap] of parts.reverse()) {
    pixelText(ctx, value, x, HERO_BASELINE, font, color, "right", "alphabetic");
    ctx.font = font;
    x -= ctx.measureText(value).width + gap;
  }
}

function modelRegions(scene) {
  const providerWidth = (layout.width - UTILITY_WIDTH) / scene.providers.length;
  const regions = [];
  scene.providers.forEach((provider, index) => regions.push({ id: provider.id, x: providerWidth * index, width: providerWidth }));
  regions.push({ id: "weather", x: layout.width - UTILITY_WIDTH, width: UTILITY_WIDTH });
  return regions;
}

export function hitTest(x, scene) {
  if (scene.mode === "models") return modelRegions(scene).find((region) => x >= region.x && x < region.x + region.width)?.id ?? "weather";
  if (x < 190) return "presence";
  if (x < 520) return "primary";
  if (x < 760) return "progress";
  return "time";
}

function renderModels(ctx, state) {
  const { scene, selected, now } = state;
  const regions = modelRegions(scene);

  regions.slice(1).forEach((region) => {
    ctx.fillStyle = LINE;
    ctx.fillRect(region.x, 0, 1, layout.height);
  });

  const selectedRegion = regions.find((region) => region.id === selected);
  if (selectedRegion) selection(ctx, selectedRegion.x, selectedRegion.width, scene.accent);

  scene.providers.forEach((provider, index) => {
    const region = regions[index];
    const x = region.x + 24;
    const right = region.x + region.width - 24;

    drawProviderMark(ctx, provider, x + 13, 32, 1.2);
    pixelText(ctx, provider.name, x + 40, 32, PIXEL.label, TEXT);
    pixelText(ctx, `${provider.remaining}%`, x - 2, 88, PIXEL.hero, TEXT);
    drawReset(ctx, provider.reset, right);

    pixelText(ctx, provider.window, x, 138);
    roundRect(ctx, x, 154, region.width - 48, 14, 7, "#151a1e");
    roundRect(ctx, x, 154, (region.width - 48) * provider.remaining / 100, 14, 7, provider.color);

    pixelText(ctx, provider.secondaryLabel, x, 194);
    pixelText(ctx, `${provider.secondary}%`, right, 194, PIXEL.label, TEXT, "right");
    roundRect(ctx, x, 210, region.width - 48, 7, 3, "#151a1e");
    roundRect(ctx, x, 210, (region.width - 48) * provider.secondary / 100, 7, 3, `${provider.color}b8`);
  });

  const utility = regions.at(-1);
  const x = utility.x + 24;
  const currentTime = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", hour12: false }).format(now);
  const parts = new Intl.DateTimeFormat("en-US", { weekday: "short", day: "2-digit", month: "short" }).formatToParts(now);
  const part = (type) => parts.find((item) => item.type === type).value.toUpperCase();
  pixelText(ctx, scene.weather.location, x, 30, PIXEL.label, TEXT);
  pixelText(ctx, currentTime, x - 2, 74, PIXEL.hero, TEXT);
  pixelText(ctx, `${part("weekday")} ${part("day")} ${part("month")}`, x, 120);
  ctx.beginPath();
  ctx.arc(x + 11, 154, 10, 0, Math.PI * 2);
  ctx.fillStyle = scene.accent;
  ctx.fill();
  pixelText(ctx, `${scene.weather.temperature}°C`, x + 32, 156, PIXEL.value, TEXT);
  pixelText(ctx, scene.weather.condition, x, 194);
  pixelText(ctx, `H ${scene.weather.high}° L ${scene.weather.low}°`, x, 222, PIXEL.label, "#5f686f");
}

function renderStatus(ctx, state) {
  const { scene, selected, now } = state;
  const [x0, x1, x2, x3, x4] = layout.columns;
  const p = layout.padding;

  for (const x of [x1, x2, x3]) { ctx.fillStyle = LINE; ctx.fillRect(x, 0, 1, layout.height); }
  const selectedIndex = ["presence", "primary", "progress", "time"].indexOf(selected);
  if (selectedIndex >= 0) selection(ctx, layout.columns[selectedIndex], layout.columns[selectedIndex + 1] - layout.columns[selectedIndex], scene.accent);

  ctx.beginPath(); ctx.arc(x0 + p + 20, 52, 25, 0, Math.PI * 2); ctx.fillStyle = `${scene.accent}16`; ctx.fill();
  ctx.beginPath(); ctx.arc(x0 + p + 20, 52, 9, 0, Math.PI * 2); ctx.fillStyle = scene.accent; ctx.fill();
  label(ctx, "STATUS", x0 + p, 152); text(ctx, scene.presenceTitle, x0 + p, 181, 22, TEXT, 650); text(ctx, scene.presenceNote, x0 + p, 202, 12, MUTED, 550);

  label(ctx, scene.primaryLabel, x1 + p, 68); text(ctx, scene.primaryTitle, x1 + p, 106, 28, TEXT, 650); text(ctx, scene.primaryNote, x1 + p, 131, 13, MUTED, 550);
  ctx.fillStyle = scene.accent; ctx.fillRect(x1 + p, 172, 150, 3); ctx.fillStyle = "#272c30"; ctx.fillRect(x1 + p + 156, 172, 115, 3);

  label(ctx, scene.progressLabel, x2 + p, 52); text(ctx, `${scene.progress}%`, x3 - p, 52, 14, scene.accent, 700, "right");
  roundRect(ctx, x2 + p, 78, x3 - x2 - p * 2, 52, 8, "#111519"); roundRect(ctx, x2 + p + 6, 84, (x3 - x2 - p * 2 - 12) * scene.progress / 100, 40, 5, scene.accent);
  text(ctx, scene.progressTitle, x2 + p, 185, 20, TEXT, 650); text(ctx, scene.progressNote, x3 - p, 185, 12, MUTED, 550, "right");

  const time = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", hour12: false }).format(now);
  const date = new Intl.DateTimeFormat("en-US", { weekday: "short", day: "2-digit", month: "short" }).format(now).toUpperCase();
  text(ctx, time, x3 + p, 77, 42, TEXT, 650); text(ctx, date, x3 + p, 198, 12, MUTED, 600);
  [5, 10, 16].forEach((height, i) => { ctx.fillStyle = scene.accent; ctx.fillRect(x4 - p + i * 6 - 14, 199 - height, 3, height); });
}

export function renderPanel(canvas, state) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, layout.width, layout.height);
  ctx.fillStyle = "#020304";
  ctx.fillRect(0, 0, layout.width, layout.height);
  if (state.scene.mode === "models") renderModels(ctx, state); else renderStatus(ctx, state);
  if (state.grid) drawGrid(ctx);
}
