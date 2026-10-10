import assert from "node:assert/strict";
import { test } from "node:test";

// The module reads document.baseURI only when a request is built, so a stub is enough here.
globalThis.document = { baseURI: "https://example.test/app/" };

const { apiUrl, describeDetail, filenameFromHeader } = await import("../../frontend/js/api.js");

test("API URLs are relative to the page, so they also work below a sub-path", () => {
  assert.equal(apiUrl("health").href, "https://example.test/app/api/health");
  const url = apiUrl("aibom/generate", { model: "Qwen/Qwen2.5-7B-Instruct", empty: "" });
  assert.equal(url.searchParams.get("model"), "Qwen/Qwen2.5-7B-Instruct");
  assert.equal(url.searchParams.has("empty"), false);
});

test("error details from FastAPI become one readable sentence", () => {
  assert.equal(describeDetail("No model named 'x' was found.", 404), "No model named 'x' was found.");
  assert.equal(
    describeDetail([{ loc: ["query", "q"], msg: "String should have at least 2 characters" }], 422),
    "q: String should have at least 2 characters",
  );
  assert.match(describeDetail(undefined, 429), /rate limiting/);
  assert.equal(describeDetail(undefined, 418), "The request failed (HTTP 418).");
});

test("download names come from Content-Disposition and are restricted to safe characters", () => {
  assert.equal(
    filenameFromHeader('attachment; filename="Qwen-Qwen2.5-7B-Instruct-aibom.pdf"'),
    "Qwen-Qwen2.5-7B-Instruct-aibom.pdf",
  );
  assert.equal(filenameFromHeader('attachment; filename="../../etc/passwd"'), "etc-passwd");
  assert.equal(filenameFromHeader('attachment; filename="..hidden"'), "hidden");
  assert.equal(filenameFromHeader("inline"), null);
  assert.equal(filenameFromHeader(null), null);
});
