import test from "node:test";
import assert from "node:assert/strict";
import { findNonRegistryPackages, findUnallowlistedModerate } from "./check-dependencies.mjs";

test("允许 workspace 链接并拒绝非官方 tarball 来源", () => {
  const lock = { packages: {
    "node_modules/frontend": { link: true, resolved: "frontend" },
    "node_modules/pkg": { resolved: "https://registry.npmmirror.com/pkg/-/pkg.tgz" },
  } };
  assert.deepEqual(findNonRegistryPackages(lock), [
    "node_modules/pkg: 非官方 registry 来源 https://registry.npmmirror.com/pkg/-/pkg.tgz",
  ]);
});

test("仅接受 allowlist 中注明的中危 advisory", () => {
  const audit = { vulnerabilities: {
    glob: { via: [{ severity: "moderate", url: "https://github.com/advisories/GHSA-allowed" }] },
    minimatch: { via: [{ severity: "moderate", url: "https://github.com/advisories/GHSA-new" }] },
  } };
  assert.deepEqual(findUnallowlistedModerate(audit, ["GHSA-allowed"]), ["minimatch: GHSA-new"]);
});
