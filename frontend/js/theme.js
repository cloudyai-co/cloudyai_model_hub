/**
 * Light and dark themes. The page follows the system setting until the reader picks one; the choice
 * is remembered in localStorage. CSS does the work: this module only sets data-theme on <html>.
 */

const STORAGE_KEY = "cloudyai-theme";

function storedChoice() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function remember(value) {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Storage can be unavailable (private mode). The choice then lasts for this page only.
  }
}

/** The theme in effect right now. */
export function currentTheme() {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Wire up the toggle button. The button shows the theme it will switch to. */
export function initTheme(button) {
  const root = document.documentElement;
  const saved = storedChoice();
  if (saved) root.dataset.theme = saved;

  const sync = () => {
    const now = currentTheme();
    const next = now === "dark" ? "light" : "dark";
    button.dataset.mode = now;
    button.setAttribute("aria-label", `Switch to ${next} theme`);
    button.title = `Switch to ${next} theme`;
    const label = button.querySelector(".label");
    if (label) label.textContent = next === "dark" ? "Dark" : "Light";
  };

  button.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    remember(next);
    sync();
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (!storedChoice()) sync();
  });
  sync();
}
