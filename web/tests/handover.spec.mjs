// LT-03, walked in a browser against the deployed URL.
//
// Two claims, and they are about people rather than about data structures.
//
// A script supervisor with forty minutes of daylight left has to be able to
// look at this page and find, without opening an agent trace, three things:
// what to do, who owns it, and where it came from. And a 1st AD standing at the
// truck has to be able to take something away that still means something on a
// phone at 06:40 the next morning, when this page is closed.
//
// So the tests read the page the way those two people read it, and the receipt
// is parsed rather than eyeballed: a packet that travels has to carry its own
// run, its own version and its own open items, or it is an anecdote.
//
//   npx playwright test --config web/playwright.config.mjs

import { expect, test } from "@playwright/test";

const URL = process.env.LASTTAKE_URL
  ?? "https://1p6s28nyf0.execute-api.eu-west-1.amazonaws.com/";

async function openFresh(page) {
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.locator("#bReset").click();
  await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });
}

test.describe("LT-03, the exception summary a role can act on", () => {
  test.describe.configure({ mode: "serial", timeout: 300_000 });

  test("it names the action, the responsible role and the source", async ({ page }) => {
    await openFresh(page);
    await page.selectOption("#role", "script_supervisor");

    const mine = page.locator(".mine");
    await expect(mine).toBeVisible();
    await expect(mine.locator("h3")).toContainText("the script supervisor");

    // Every line is an action, and beside it the role and the record it came
    // from. Not a finding id, not a confidence score, not a trace.
    const items = mine.locator("ol li");
    expect(await items.count()).toBeGreaterThan(0);
    const first = items.first();
    await expect(first.locator(".act")).not.toBeEmpty();
    await expect(first.locator(".from")).toContainText("read from");

    // And what is not theirs is named as somebody else's rather than hidden,
    // because "nothing for me" and "nothing open" are different facts.
    await expect(mine.locator(".others")).toContainText("Waiting on somebody else");
  });

  test("it follows the authority table when the role changes", async ({ page }) => {
    await openFresh(page);

    await page.selectOption("#role", "script_supervisor");
    const supervisor = await page.locator(".mine ol li").count();

    await page.selectOption("#role", "dit");
    await expect(page.locator(".mine h3")).toContainText("the DIT");
    const dit = await page.locator(".mine ol li").count();

    // Different chairs own different checks. If these matched, the summary
    // would not be reading the policy at all.
    expect(dit).not.toBe(supervisor);
    await expect(page.locator(".mine")).toContainText("read from");
  });

  test("it never prints a clearance, even with nothing assigned", async ({ page }) => {
    await openFresh(page);
    // Production owns the rights exception and may not accept it away, so this
    // chair reliably has items; the assertion below is about wording that must
    // hold in every state of the panel.
    await page.selectOption("#role", "production_coordinator");
    const text = (await page.locator(".mine").innerText()).toLowerCase();
    for (const clearance of ["clear to shoot", "no issues found", "rules verified",
                             "safe to wrap."]) {
      expect(text).not.toContain(clearance);
    }
  });
});

test.describe("LT-03, a receipt that survives leaving the page", () => {
  test.describe.configure({ mode: "serial", timeout: 300_000 });

  test("the copied packet carries its run, its version and what is still open",
    async ({ page }) => {
      await openFresh(page);
      await page.selectOption("#role", "script_supervisor");

      const run = await page.evaluate(
        () => JSON.parse(localStorage.getItem("lasttake.run")).run_id,
      );

      await page.locator("#bReceipt").click();
      await expect(page.locator("#receiptBox")).toBeVisible({ timeout: 90_000 });

      // Parse what a person would actually paste into an email. This is the
      // assertion: not that a box appeared, but that its contents stand alone.
      const packet = JSON.parse(await page.locator("#receiptText").innerText());
      expect(packet.run_id).toBe(run);
      expect(packet.schema).toBe("lasttake/receipt/v1");
      expect(packet.policy_version).toBeTruthy();
      expect(packet.package_revision_digest).toHaveLength(64);
      expect(packet.record_sha256).toHaveLength(64);

      // The limitations travel with it. A short document that lists problems
      // reads as a clearance to somebody who did not watch it being made.
      expect(packet.what_this_does_not_say.join(" ")).toContain("creatively complete");
      expect(packet.synthetic_corpus_notice.toLowerCase()).toContain("fictional");

      // And every open item answers the three questions on its own.
      expect(packet.still_open_count).toBeGreaterThan(0);
      for (const row of packet.still_open) {
        expect(row.next_action).toBeTruthy();
        expect(row.responsible_role).toBeTruthy();
        expect(row.read_from.length).toBeGreaterThan(0);
      }
    });

  test("an accepted exception still travels on the receipt as open", async ({ page }) => {
    await openFresh(page);
    await page.selectOption("#role", "script_supervisor");

    const conflict = page.locator('.card[data-req="CR-01"]');
    await conflict.locator('button[data-action="accept_exception"]').click();
    await expect(conflict.locator(".decided")).toContainText("accept exception", {
      timeout: 90_000,
    });

    await page.locator("#bReceipt").click();
    await expect(page.locator("#receiptBox")).toBeVisible({ timeout: 90_000 });
    const packet = JSON.parse(await page.locator("#receiptText").innerText());

    const row = packet.still_open.find((r) => r.finding_id.endsWith(":con:CR-01"));
    expect(row).toBeTruthy();
    // Somebody signed for it. That is not the same as it being fixed, and the
    // packet has to say so where editorial will read it.
    expect(row.a_human_decided.action).toBe("accept_exception");
    expect(row.a_human_decided.role).toBe("script_supervisor");
    expect(row.a_human_decided.still_open_because).toContain("not a fixed one");
  });
});
