import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { findBoundaryViolations } from "./check-boundaries.mjs";

test("拒绝 core 越层依赖和领域 DTO 框架，仅允许配置边界使用 Pydantic", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "rai-boundary-"));
  try {
    const core = path.join(root, "backend/src/core");
    const shared = path.join(root, "frontend/src/shared");
    mkdirSync(core, { recursive: true });
    mkdirSync(shared, { recursive: true });
    writeFileSync(path.join(core, "bad.py"), "from service.jobs import run\n");
    writeFileSync(path.join(core, "model.py"), "from pydantic import BaseModel\n");
    writeFileSync(path.join(core, "config.py"), "from pydantic import BaseModel\n");
    writeFileSync(path.join(shared, "bad.ts"), 'import { x } from "../../features/jobs/x";\n');
    const violations = findBoundaryViolations(root);
    assert.equal(violations.length, 3);
    assert.equal(violations.some((item) => item.includes("config.py")), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
