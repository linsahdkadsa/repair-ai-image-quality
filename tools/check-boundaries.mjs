import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

function filesUnder(directory) {
  if (!statSync(directory, { throwIfNoEntry: false })?.isDirectory()) return [];
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(target) : [target];
  });
}

export function findBoundaryViolations(root) {
  const violations = [];
  const core = path.join(root, "backend/src/core");
  for (const file of filesUnder(core).filter((item) => item.endsWith(".py"))) {
    const source = readFileSync(file, "utf8");
    if (/^\s*(?:from\s+(?:api|service|repo|infra)(?:\.|\s)|import\s+(?:api|service|repo|infra)(?:\.|\s))/m.test(source)) {
      violations.push(`${path.relative(root, file)}: core 不得依赖外层模块`);
    }
    const importsFastApi = /^\s*(?:from|import)\s+fastapi(?:\.|\s)/m.test(source);
    const importsPydantic = /^\s*(?:from|import)\s+pydantic(?:\.|\s)/m.test(source);
    const isConfigurationBoundary = path.basename(file) === "config.py";
    if (importsFastApi || (importsPydantic && !isConfigurationBoundary)) {
      violations.push(`${path.relative(root, file)}: core 不得依赖 HTTP/DTO 框架`);
    }
  }

  const shared = path.join(root, "frontend/src/shared");
  for (const file of filesUnder(shared).filter((item) => /\.[jt]sx?$/.test(item))) {
    const source = readFileSync(file, "utf8");
    if (/(?:from\s*|import\s*\()["'][^"']*(?:features|pages)(?:\/|["'])/.test(source)) {
      violations.push(`${path.relative(root, file)}: shared 不得依赖业务模块`);
    }
  }
  return violations;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const violations = findBoundaryViolations(fileURLToPath(new URL("../", import.meta.url)));
  if (violations.length) {
    console.error(violations.join("\n"));
    process.exit(1);
  }
  console.log("架构边界检查通过");
}
