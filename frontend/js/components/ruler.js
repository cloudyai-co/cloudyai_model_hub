/**
 * Completeness ruler: a 0 to 100 scale split into three bands, with a pointer at the score.
 * It is drawn as SVG so it scales with its column. Colours come from CSS classes (see app.css).
 */

import { svg } from "../dom.js";

const BANDS = [
  { from: 0, to: 50, level: "sparse", label: "Sparse" },
  { from: 50, to: 80, level: "partial", label: "Partial" },
  { from: 80, to: 100, level: "strong", label: "Strong" },
];

// Drawn in a narrow coordinate space so that the labels render close to their CSS size.
const WIDTH = 360;
const HEIGHT = 74;
const BAR_TOP = 18;
const BAR_HEIGHT = 20;
const LEFT = 1;
const SPAN = WIDTH - 2;

const x = (value) => LEFT + (SPAN * value) / 100;

/**
 * @param {number} score 0 to 100.
 * @param {string} level "strong" | "partial" | "sparse".
 * @returns {SVGSVGElement}
 */
export function completenessRuler(score, level) {
  const value = Math.max(0, Math.min(100, Number(score) || 0));
  const label = `Completeness ${value} of 100, ${level}.`;
  const root = svg(
    "svg",
    {
      class: "ruler",
      viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
      role: "img",
      "aria-label": label,
    },
    svg("title", {}, label),
  );

  for (const band of BANDS) {
    root.append(
      svg("rect", {
        class: `band-${band.level}`,
        x: x(band.from),
        y: BAR_TOP,
        width: x(band.to) - x(band.from),
        height: BAR_HEIGHT,
      }),
    );
    root.append(
      svg(
        "text",
        { class: "ruler-band-label", x: x(band.from) + 6, y: BAR_TOP + BAR_HEIGHT / 2 + 3.2 },
        band.label.toUpperCase(),
      ),
    );
  }

  root.append(svg("rect", { class: "ruler-frame", x: LEFT, y: BAR_TOP, width: SPAN, height: BAR_HEIGHT }));

  for (let mark = 0; mark <= 100; mark += 10) {
    const major = mark % 50 === 0 || mark === 80;
    const top = BAR_TOP + BAR_HEIGHT;
    root.append(svg("line", { class: "ruler-tick", x1: x(mark), x2: x(mark), y1: top, y2: top + (major ? 7 : 4) }));
  }

  for (const mark of [0, 50, 80, 100]) {
    const anchor = mark === 0 ? "start" : mark === 100 ? "end" : "middle";
    root.append(
      svg(
        "text",
        { class: "ruler-label", x: x(mark), y: BAR_TOP + BAR_HEIGHT + 20, "text-anchor": anchor },
        String(mark),
      ),
    );
  }

  const pointer = x(value);
  root.append(
    svg("line", {
      class: "ruler-marker",
      x1: pointer,
      x2: pointer,
      y1: BAR_TOP - 10,
      y2: BAR_TOP + BAR_HEIGHT + 7,
    }),
    svg("polygon", {
      class: "ruler-pointer",
      points: `${pointer - 4.5},${BAR_TOP - 10} ${pointer + 4.5},${BAR_TOP - 10} ${pointer},${BAR_TOP - 2}`,
    }),
  );
  return root;
}
