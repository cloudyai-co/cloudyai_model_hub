import assert from "node:assert/strict";
import { test } from "node:test";
import { parseHash, routeHref } from "../../frontend/js/router.js";

test("hash routes map to known views", () => {
  assert.equal(parseHash("#/").name, "overview");
  assert.equal(parseHash("").name, "overview");
  assert.equal(parseHash("#/aibom").name, "aibom");
  assert.equal(parseHash("#/selection").name, "selection");
});

test("unknown paths fall back to the overview instead of rendering nothing", () => {
  assert.equal(parseHash("#/admin").name, "overview");
  assert.equal(parseHash("#/../../etc").name, "overview");
  assert.equal(parseHash("#/constructor").name, "overview");
});

test("query parameters survive a round trip, including slashes", () => {
  const href = routeHref("aibom", { model: "Qwen/Qwen2.5-7B-Instruct" });
  assert.equal(href, "#/aibom?model=Qwen%2FQwen2.5-7B-Instruct");
  const parsed = parseHash(href);
  assert.equal(parsed.name, "aibom");
  assert.equal(parsed.params.get("model"), "Qwen/Qwen2.5-7B-Instruct");
});

test("empty parameters are omitted from links", () => {
  assert.equal(routeHref("selection", { q: "", model: "org/m", dtype: undefined }), "#/selection?model=org%2Fm");
  assert.equal(routeHref("overview"), "#/");
});
