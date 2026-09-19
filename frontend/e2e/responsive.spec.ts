import { expect, test } from "@playwright/test";

import {
  driveToValidatedResult,
  horizontalOverflowPx,
  installApiMocks,
} from "./support/harness";

const VIEWPORTS = [
  { label: "desktop", width: 1440, height: 900, railScrolls: false },
  { label: "tablet", width: 1024, height: 768, railScrolls: false },
  { label: "mobile", width: 390, height: 844, railScrolls: true },
] as const;

const STAGES = [
  "Ingest",
  "Inspect",
  "Optimise",
  "Validate",
  "Explain",
  "Calendar",
  "Export",
] as const;

for (const viewport of VIEWPORTS) {
  test(`${viewport.label} ${viewport.width}x${viewport.height} keeps the page within the viewport and scrolls the tab rail`, async ({
    page,
  }) => {
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await installApiMocks(page);
    await driveToValidatedResult(page);

    expect(await horizontalOverflowPx(page)).toBeLessThanOrEqual(1);

    const metrics = await page.locator(".workflow-tabs").evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    }));
    if (viewport.railScrolls) {
      expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth);
    } else {
      expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
    }

    // The widest panel decides page width. Visit every stage and re-check.
    for (const stage of STAGES) {
      await page.getByRole("tab", { name: new RegExp(stage) }).click();
      await expect(
        page.locator(`#workflow-panel-${stage.toLowerCase()}`),
      ).toBeVisible();
      expect(await horizontalOverflowPx(page)).toBeLessThanOrEqual(1);
    }
  });
}
