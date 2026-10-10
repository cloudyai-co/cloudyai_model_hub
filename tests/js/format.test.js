import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EMPTY,
  formatBytes,
  formatCompact,
  formatDate,
  formatGigabytes,
  formatParameters,
  formatTimestamp,
  formatVram,
  levelLabel,
  parseWeightDtypes,
  shortHash,
} from "../../frontend/js/format.js";

test("byte sizes use binary units, as in the PDF", () => {
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1024), "1.0 KB");
  assert.equal(formatBytes(15_242_807_270), "14.2 GB");
  assert.equal(formatBytes(-1), EMPTY);
  assert.equal(formatBytes(null), EMPTY);
});

test("parameter counts switch between M and B", () => {
  assert.equal(formatParameters(7_615_616_512), "7.62 B");
  assert.equal(formatParameters(350_000_000), "350.0 M");
  assert.equal(formatParameters(0), EMPTY);
  assert.equal(formatParameters("7"), EMPTY);
});

test("accelerator memory is whole gigabytes", () => {
  assert.equal(formatVram(80), "80 GB");
  assert.equal(formatVram(192.0), "192 GB");
  assert.equal(formatVram(0), EMPTY);
});

test("gigabyte estimates keep one decimal below 100", () => {
  assert.equal(formatGigabytes(17.32), "17.3 GB");
  assert.equal(formatGigabytes(97.69), "97.7 GB");
  assert.equal(formatGigabytes(250.4), "250 GB");
});

test("compact counts for downloads and likes", () => {
  assert.equal(formatCompact(8_105_080), "8.1M");
  assert.equal(formatCompact(2417), "2.4K");
  assert.equal(formatCompact(undefined), EMPTY);
});

test("dates and timestamps are shown in ISO form", () => {
  assert.equal(formatDate("2025-01-12T02:10:10.000Z"), "2025-01-12");
  assert.equal(formatDate("not a date"), EMPTY);
  assert.equal(formatTimestamp("2026-10-09T12:00:00Z"), "2026-10-09 12:00 UTC");
  assert.equal(formatTimestamp(""), EMPTY);
});

test("short hashes are cut and marked", () => {
  assert.equal(shortHash("a09a35458c702b33eeacc393d103063234e8bc28"), "a09a35458c70…");
  assert.equal(shortHash("abc", 2), "ab…");
  assert.equal(shortHash(""), EMPTY);
});

test("weight dtypes are parsed and sorted by size", () => {
  assert.deepEqual(parseWeightDtypes("F32:12,BF16:7615616512"), [
    { dtype: "BF16", count: 7615616512 },
    { dtype: "F32", count: 12 },
  ]);
  assert.deepEqual(parseWeightDtypes("garbage"), []);
  assert.deepEqual(parseWeightDtypes(undefined), []);
});

test("completeness labels", () => {
  assert.equal(levelLabel("strong"), "Strong");
  assert.equal(levelLabel("unknown"), EMPTY);
});
