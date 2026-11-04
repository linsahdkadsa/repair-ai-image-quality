import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { checkHandoff } from "./check-handoff.mjs";

function fixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), "rai-handoff-"));
  mkdirSync(path.join(root, "docs/handoffs"), { recursive: true });
  mkdirSync(path.join(root, "docs/evidence/P02"), { recursive: true });
  const content = "verified artifact\n";
  writeFileSync(path.join(root, "artifact.txt"), content);
  writeFileSync(path.join(root, "docs/evidence/P02/test.txt"), "PASS\n");
  const output = { path: "artifact.txt", bytes: Buffer.byteLength(content), sha256: createHash("sha256").update(content).digest("hex") };
  for (const phase of ["P00", "P01"]) {
    writeFileSync(path.join(root, `docs/handoffs/${phase}.json`), JSON.stringify({ phase, status: "accepted", outputs: [output] }));
  }
  writeFileSync(path.join(root, "docs/handoffs/P02.json"), JSON.stringify({ phase: "P02", status: "accepted", previousHandoff: "docs/handoffs/P01.json", outputs: [output], verification: [{ command: "test", exitCode: 0, report: "docs/evidence/P02/test.txt" }] }));
  return root;
}

test("拒绝缺失产物", () => {
  const root = fixture();
  try {
    rmSync(path.join(root, "artifact.txt"));
    assert.ok(checkHandoff(root, "P02").some((error) => error.includes("缺少输出")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("拒绝哈希错误及失败证据", () => {
  const root = fixture();
  try {
    const handoffPath = path.join(root, "docs/handoffs/P02.json");
    const handoff = JSON.parse(readFileSync(handoffPath, "utf8"));
    handoff.outputs[0].sha256 = "0".repeat(64);
    handoff.verification[0].exitCode = 1;
    writeFileSync(handoffPath, JSON.stringify(handoff));
    const errors = checkHandoff(root, "P02");
    assert.ok(errors.some((error) => error.includes("SHA-256 不符")));
    assert.ok(errors.some((error) => error.includes("验证未通过")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("拒绝缺少前置交接", () => {
  const root = fixture();
  try {
    rmSync(path.join(root, "docs/handoffs/P01.json"));
    assert.ok(checkHandoff(root, "P02").some((error) => error.includes("P01.json")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("拒绝缺失的验证报告", () => {
  const root = fixture();
  try {
    rmSync(path.join(root, "docs/evidence/P02/test.txt"));
    assert.ok(checkHandoff(root, "P02").some((error) => error.includes("缺少验证报告")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

