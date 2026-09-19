import { expect, test } from "@playwright/test";

import {
  blockedValidatorReportRead,
  driveToValidatedResult,
  exportScenarioA,
  installApiMocks,
} from "./support/harness";

// AT-15: a judge uploads an unseen eight-CSV instance and drives Ingest ->
// Inspect -> Optimise -> Validate -> Explain -> Export entirely in the browser.
// The solver, database and worker are replaced by route mocks, so this proves
// the browser workflow and the export gate, not the solver itself.
test.describe("AT-15 hidden-instance judge workflow", () => {
  test("uploads, validates and exports a held-out instance without a real solver", async ({
    page,
  }) => {
    const state = await installApiMocks(page);

    await driveToValidatedResult(page);

    await expect(
      page.getByRole("heading", { name: "Validator gate" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Score components" }),
    ).toBeVisible();
    await expect(page.getByText("PROVISIONAL").first()).toBeVisible();
    expect(state.jobPolls).toBeGreaterThan(0);

    // Stage 5 · Explain renders the deterministic schedule evidence.
    await page.getByRole("tab", { name: /Explain/ }).click();
    await expect(page.getByLabel("Scenario A schedule evidence")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Activity explanations" }),
    ).toBeVisible();

    // Stage 6 · Export is gated open by the validator and downloads a zip.
    const download = await exportScenarioA(page);
    expect(download.suggestedFilename()).toBe("scenario-A.zip");
    await expect(page.getByText("Downloaded scenario-A.zip")).toBeVisible();
    expect(state.exportRequests).toBe(1);
  });

  test("keeps export blocked when the validator gate fails", async ({ page }) => {
    const state = await installApiMocks(page, {
      report: blockedValidatorReportRead,
    });

    await driveToValidatedResult(page);

    await expect(page.getByText("BLOCKED").first()).toBeVisible();

    await page.getByRole("tab", { name: /Export/ }).click();
    await expect(
      page.getByRole("heading", { name: "Submission export" }),
    ).toBeVisible();
    await expect(page.getByText("Export is withheld")).toBeVisible();
    const downloadButton = page.getByRole("button", { name: /Download .*zip/ });
    await expect(downloadButton).toBeDisabled();
    expect(state.exportRequests).toBe(0);
  });
});
