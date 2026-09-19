import { expect, test } from "@playwright/test";

import {
  driveToValidatedResult,
  installApiMocks,
  uploadHiddenInstance,
} from "./support/harness";

const LOCKED_STAGES = ["Optimise", "Validate", "Explain", "Calendar", "Export"] as const;

test.describe("workflow tab keyboard navigation", () => {
  test("marks future stages locked and skips them with arrows, Home and End", async ({
    page,
  }) => {
    // The network request is forced to fail, so only Ingest and Inspect become
    // available and every later stage stays locked.
    await installApiMocks(page, { networkStatus: 500 });
    await page.goto("/");
    await uploadHiddenInstance(page);

    await expect(page.getByRole("tab", { name: /Inspect/ })).toBeEnabled();
    for (const stage of LOCKED_STAGES) {
      const tab = page.getByRole("tab", { name: new RegExp(stage) });
      await expect(tab).toBeDisabled();
      await expect(tab).toHaveAttribute("aria-disabled", "true");
    }

    await page.getByRole("tab", { name: /Ingest/ }).click();
    await expect(page.getByRole("tab", { name: /Ingest/ })).toBeFocused();

    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: /Inspect/ })).toBeFocused();

    // ArrowRight from the last available stage wraps past every locked tab.
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: /Ingest/ })).toBeFocused();

    await page.keyboard.press("End");
    await expect(page.getByRole("tab", { name: /Inspect/ })).toBeFocused();

    await page.keyboard.press("Home");
    await expect(page.getByRole("tab", { name: /Ingest/ })).toBeFocused();

    await page.keyboard.press("ArrowLeft");
    await expect(page.getByRole("tab", { name: /Inspect/ })).toBeFocused();
  });

  test("traverses all seven stages and shows each stage panel", async ({ page }) => {
    await installApiMocks(page);
    await driveToValidatedResult(page);

    await page.getByRole("tab", { name: /Ingest/ }).click();
    await expect(page.locator("#workflow-panel-ingest")).toBeVisible();

    const forward: Array<[string, string]> = [
      ["ArrowRight", "Inspect"],
      ["ArrowRight", "Optimise"],
      ["ArrowRight", "Validate"],
      ["ArrowRight", "Explain"],
      ["ArrowRight", "Calendar"],
      ["ArrowRight", "Export"],
      ["ArrowRight", "Ingest"],
    ];
    for (const [key, stage] of forward) {
      await page.keyboard.press(key);
      await expect(page.getByRole("tab", { name: new RegExp(stage) })).toBeFocused();
      await expect(
        page.locator(`#workflow-panel-${stage.toLowerCase()}`),
      ).toBeVisible();
    }

    await page.keyboard.press("End");
    await expect(page.getByRole("tab", { name: /Export/ })).toBeFocused();
    await expect(page.locator("#workflow-panel-export")).toBeVisible();

    await page.keyboard.press("Home");
    await expect(page.getByRole("tab", { name: /Ingest/ })).toBeFocused();
    await expect(page.locator("#workflow-panel-ingest")).toBeVisible();

    await page.keyboard.press("ArrowLeft");
    await expect(page.getByRole("tab", { name: /Export/ })).toBeFocused();
  });

  test("automatic stage changes move focus into the newly shown panel", async ({
    page,
  }) => {
    await installApiMocks(page);
    await page.goto("/");

    await uploadHiddenInstance(page);
    await expect(page.locator("#workflow-panel-inspect")).toBeFocused();

    await page.getByRole("tab", { name: /Optimise/ }).click();
    await page.getByRole("button", { name: /Dispatch A/ }).click();

    await expect(page.locator("#workflow-panel-validate")).toBeVisible();
    await expect(page.locator("#workflow-panel-validate")).toBeFocused();
  });
});
