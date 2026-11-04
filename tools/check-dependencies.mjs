import { readFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const rootPath = fileURLToPath(new URL("../", import.meta.url));

export function findNonRegistryPackages(lock) {
  return Object.entries(lock.packages ?? {}).flatMap(([name, dependency]) => {
    if (!name || dependency.link || !dependency.resolved) return [];
    return dependency.resolved.startsWith("https://registry.npmjs.org/")
      ? []
      : [`${name}: 非官方 registry 来源 ${dependency.resolved}`];
  });
}

export function findUnallowlistedModerate(audit, allowlist) {
  const allowed = new Set(allowlist);
  const findings = new Set();
  for (const [name, vulnerability] of Object.entries(audit.vulnerabilities ?? {})) {
    for (const advisory of vulnerability.via ?? []) {
      if (typeof advisory !== "object" || advisory.severity !== "moderate" || !advisory.url) continue;
      const id = new URL(advisory.url).pathname.split("/").at(-1);
      if (!allowed.has(id)) findings.add(`${name}: ${id}`);
    }
  }
  return [...findings].sort();
}

export function checkDependencies() {
  const lockPath = fileURLToPath(new URL("../package-lock.json", import.meta.url));
  const lock = JSON.parse(readFileSync(lockPath, "utf8"));
  const allowlistPath = new URL("../docs/evidence/P02/dependency-audit-allowlist.json", import.meta.url);
  const allowlist = JSON.parse(readFileSync(allowlistPath, "utf8"));
  const npmExecPath = process.env.npm_execpath;
  const audit = spawnSync(npmExecPath ? process.execPath : "npm", [
    ...(npmExecPath ? [npmExecPath] : []),
    "audit", "--json", "--audit-level=high", "--registry=https://registry.npmjs.org/",
  ], { cwd: rootPath, encoding: "utf8", windowsHide: true });
  const problems = findNonRegistryPackages(lock);
  let report;
  try {
    report = JSON.parse(audit.stdout);
  } catch {
    problems.push(`npm audit 无法返回 JSON (exit ${audit.status}): ${audit.stderr.trim()}`);
  }
  if (audit.status !== 0) problems.push(`npm audit 未通过 (exit ${audit.status})`);
  if (report) problems.push(...findUnallowlistedModerate(report, allowlist.allowedAdvisories));
  return { problems, allowlistedCount: allowlist.allowedAdvisories.length };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { problems, allowlistedCount } = checkDependencies();
  if (problems.length) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log(`依赖检查通过: ${allowlistedCount} 个中危 advisory 在显式 allowlist 中；锁文件仅使用官方 registry`);
}
