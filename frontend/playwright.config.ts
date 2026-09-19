import { execFileSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

// Playwright's bundled browser download is not available on every platform
// (NixOS in particular). The suite can launch a Nix-provided chromium instead.
// Only Nix store paths are auto-detected so every other platform, CI included,
// falls back to Playwright's own downloaded browser. Set
// PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH to force any other binary.
function resolveChromiumExecutable(): string | undefined {
  const override = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (override) {
    return existsSync(override) ? override : undefined;
  }

  const candidates = new Set<string>();
  for (const name of ["chromium", "chromium-browser"]) {
    try {
      const found = execFileSync("sh", ["-c", `command -v ${name}`], {
        encoding: "utf8",
      }).trim();
      if (found) candidates.add(found);
    } catch {
      // Not on PATH, try the next candidate.
    }
  }
  for (const fallback of ["/run/current-system/sw/bin/chromium"]) {
    if (existsSync(fallback)) candidates.add(fallback);
  }

  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue;
    let resolved = candidate;
    try {
      resolved = realpathSync(candidate);
    } catch {
      // Keep the unresolved path.
    }
    if (resolved.startsWith("/nix/store/")) return candidate;
  }

  return undefined;
}

const chromiumExecutable = resolveChromiumExecutable();

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.artifacts/results",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [["github"], ["list"]]
    : [["list"], ["html", { outputFolder: "e2e/.artifacts/report", open: "never" }]],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    launchOptions: chromiumExecutable
      ? { executablePath: chromiumExecutable }
      : {},
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command:
      "npm run build && npm run preview -- --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
