// Browser fault injection only; never contacts the live application.
import { expect, test } from "@playwright/test";
import { waitForIdle, waitForApproval, walkToTurnover } from "../support/walk.mjs";

for (const mode of ["busy", "pending", "unapproved", "unpublished", "pickup-unapproved"]) {
  test(`the completion wait refuses ${mode} state`, async ({ page }) => {
    await page.setContent('<div id="turnbox"></div>');
    await page.evaluate((state) => {
      window.BUSY = state === "busy";
      window.PENDING = state === "pending" ? { reason: { kind: "wrap" } } : null;
      window.STATE = { wrap_approved: state !== "unapproved" };
      window.PICKUP_APPROVED = false;
      if (state !== "unpublished") document.getElementById("turnbox").textContent = "Published and sealed";
    }, mode);
    // A short fault-injection deadline, not a change to any product-test budget.
    page.setDefaultTimeout(150);
    await expect(waitForApproval(page, mode !== "pickup-unapproved")).rejects.toThrow(/Timeout/);
    if (mode === "busy") await expect(waitForIdle(page)).rejects.toThrow(/Timeout/);
  });
}

test("delayed publication completes without clicking the disabled final step", async ({ page }) => {
  await page.setContent('<button id="go">Next: Turnover to editorial</button><div id="pause"></div><div id="turnbox"></div>');
  await page.evaluate(() => {
    window.BUSY = false;
    window.PENDING = null;
    window.STATE = { wrap_approved: false };
    window.nextClicks = 0;
    document.getElementById("go").onclick = () => {
      window.nextClicks += 1;
      window.PENDING = { reason: { kind: "wrap" } };
      document.getElementById("pause").innerHTML = '<button id="bYes">Approve</button>';
      document.getElementById("bYes").onclick = () => {
        window.BUSY = true;
        window.approvalStarted = true;
        document.getElementById("go").disabled = true;
        document.getElementById("pause").innerHTML = "";
      };
    };
  });
  const walking = walkToTurnover(page);
  await page.waitForFunction(() => window.approvalStarted === true);
  // The approval response lands first; the separate turnover is still absent.
  await page.evaluate(() => {
    window.STATE.wrap_approved = true;
    window.PENDING = null;
    window.BUSY = false;
  });
  // Negative control: the old loop's next click cannot complete in this state.
  await expect(page.locator("#go").click({ timeout: 150 })).rejects.toThrow(/Timeout/);
  await page.evaluate(() => {
    document.getElementById("turnbox").textContent = "Published and sealed";
    document.getElementById("go").textContent = "Walkthrough complete";
  });
  await walking;
  expect(await page.evaluate(() => window.nextClicks)).toBe(1);
  await expect(page.locator("#go")).toBeDisabled();
});
