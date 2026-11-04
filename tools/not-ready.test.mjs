import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("尚未实现的门禁必须失败而非空成功", () => {
  const script = fileURLToPath(new URL("./not-ready.mjs", import.meta.url));
  const result = spawnSync(process.execPath, [script, "E2E", "P05"], { encoding: "utf8" });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /尚未在 P05 实现/);
});
