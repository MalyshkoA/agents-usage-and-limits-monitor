import { cells, scenes } from "./model.js";
import { hitTest, renderPanel } from "./renderer.js";

const canvas = document.querySelector("#panelCanvas");
const body = document.body;
const root = document.documentElement;
const state = { scene: scenes.limits, selected: "limits", grid: false, now: new Date() };

function render() { renderPanel(canvas, state); }

function selectCell(key) {
  state.selected = key;
  const [title, hint] = cells[key];
  document.querySelector("#selectedCell").textContent = title;
  document.querySelector("#selectedHint").textContent = hint;
  render();
}

document.querySelectorAll(".scenario").forEach((button) => {
  button.addEventListener("click", () => {
    state.scene = scenes[button.dataset.scene];
    state.selected = state.scene.mode === "models" ? "limits" : "primary";
    root.style.setProperty("--accent", state.scene.accent);
    document.querySelectorAll(".scenario").forEach((item) => item.classList.toggle("active", item === button));
    selectCell(state.selected);
  });
});

canvas.addEventListener("click", (event) => {
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * canvas.width / rect.width;
  selectCell(hitTest(x, state.scene));
});

document.querySelector("#toggleGrid").addEventListener("click", (event) => {
  state.grid = !state.grid;
  event.currentTarget.setAttribute("aria-pressed", String(state.grid));
  render();
});

document.querySelector("#toggleFullscreen").addEventListener("click", () => body.classList.toggle("fullscreen-stage"));

document.querySelector("#brightness").addEventListener("input", (event) => {
  const value = Number(event.target.value);
  root.style.setProperty("--display-brightness", value / 100);
  document.querySelector("#brightnessValue").textContent = `${value}%`;
});

selectCell("limits");
render();
// Panel pixel fonts must be loaded before the canvas can use them.
Promise.all(["12x24", "16x32", "32x64"].map((size) => document.fonts.load(`10px "Spleen ${size}"`))).then(render);
setInterval(() => { state.now = new Date(); render(); }, 15000);
