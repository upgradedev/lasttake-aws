// The exact path the video shows, walked by a browser against the live URL.
//
// Gate C5 asks for one browser test walking the journey the video shows, and
// until now that walk existed only as something I did by hand through a browser
// console, repeatedly, and never wrote down. The path the film will be cut from
// was the one path nothing protected.
//
// It runs against the deployed site on purpose. tools/uptime_check.py already
// asserts the API end to end; what nobody was asserting is that the page a judge
// opens still does what it is supposed to do when you click it. Those are
// different failures: the fabricated evaluation modal that reached the live URL
// called no API at all, so an API check could not see it.
//
//   npx playwright test --config web/playwright.config.mjs

import { expect, test } from "@playwright/test";

const URL = process.env.LASTTAKE_URL
  ?? "https://1p6s28nyf0.execute-api.eu-west-1.amazonaws.com/";

// Sentences this product does not say. A page that gives a clearance has broken
// the one rule the whole thing exists to enforce, and no other assertion here
// matters if this one fails.
const NEVER = ["CLEAR TO SHOOT", "rules verified", "Multi-Agent Evaluation", "legally cleared"];

test.describe("one shoot day, on the deployed page", () => {
  test.describe.configure({ mode: "serial", timeout: 240_000 });

  test("the page opens on the scene and gives no clearance", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });
    await expect(page.locator(".beat").first()).toBeVisible({ timeout: 60_000 });

    const body = (await page.locator("body").innerText()).toLowerCase();
    for (const phrase of NEVER) {
      expect(body, `the page printed ${phrase}`).not.toContain(phrase.toLowerCase());
    }

    // The lined script is the whole scene, drawn before any check has finished.
    await expect(page.locator(".beat")).toHaveCount(36);
    await expect(page.locator(".take")).toHaveCount(40);
    await expect(page.locator(".synth")).toContainText("Synthetic data");
    // And the process boundary is on screen without scrolling for it.
    await expect(page.locator(".proof")).toContainText("container");
  });

  test("the verdict lands, and it is the count we publish", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });
    await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });
    await expect(page.locator("#vhead")).toHaveText("Not ready to wrap.");
    await expect(page.locator("#vsub")).toContainText(
      "Of 34 required beats, 31 covered with evidence",
    );
    await expect(page.locator("#exchead")).toContainText("Before you wrap");
  });

  test("an exception points at the lines it is about, in both directions", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.locator('.card[data-req="B-17"]').waitFor({ timeout: 90_000 });

    await page.locator('.card[data-req="B-17"] h3').click();
    await expect(page.locator('.beat[data-beat="B-17"]')).toHaveClass(/linked/);

    // The continuity conflict is filed against a reference and lights three beats.
    await page.locator('.card[data-req="CR-01"] h3').click();
    await expect(page.locator(".beat.linked")).toHaveCount(3);

    // And from a beat back to the exception that names it.
    //
    // Click the slug, which is the line of script, because that is what a person
    // clicks. Clicking the beat element's centre is not the same thing: a beat
    // that has takes has its centre over the take chips, so the hit test lands
    // on a slate and opens the inspector instead. The first run of this test
    // found exactly that, and my own hand check could not have: dispatching
    // click() on the div from a console skips hit testing altogether and always
    // "worked".
    await page.locator('.beat[data-beat="B-09"] .slug').click();
    await expect(page.locator('.card[data-req="BG-07"]')).toHaveClass(/linked/);
    await expect(page.locator("#drawer")).not.toHaveClass(/on/);

    // The orphan-shot advisory names no requirement, so it is about no lines and
    // must never be what a beat links to. It was: `b.continuity_ref === null` is
    // true on 29 of 36 beats, so the advisory matched almost the whole scene and
    // clicking a beat lit nothing.
    const advisory = page.locator(".card").filter({ hasText: "shot plan and the script have drifted" });
    await expect(advisory).toHaveCount(1);
    await expect(advisory).not.toHaveAttribute("data-req", /./);
    await expect(page.locator(".beat.linked")).toHaveCount(1);
  });

  test("a slate opens the two records side by side", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.locator('.take[data-take="T-013"]').waitFor({ timeout: 90_000 });
    await page.locator('.take[data-take="T-013"]').click();

    const drawer = page.locator("#drawer");
    await expect(drawer).toHaveClass(/on/);
    // The sidecar says one media id and the camera report says another.
    await expect(drawer).toContainText("A002R2B13");
    await expect(drawer).toContainText("report says A002R2B1X");
    await expect(drawer).toContainText("disagree on media id");

    // And no model attribution, because there is no model in this answer.
    // Metadata is arithmetic over two documents and never calls one, so a
    // "read by" line here would be the interface inventing a provenance. This
    // assertion was the other way round on its first run, asserting the
    // interpreter appeared, which was my assumption about the product rather
    // than the product.
    await expect(drawer).not.toContainText("Read by");

    // The continuity conflict is the one that does ask a model, and it names
    // whichever interpreter actually produced the reading. On the live URL that
    // is the offline lexical one, never Bedrock, and the page says so.
    await page.locator("#scrim").click();
    await page.locator('.take[data-take="T-026"]').click();
    const conflict = page.locator("#drawer");
    await expect(conflict).toHaveClass(/on/);
    await expect(conflict).toContainText("Read by offline-lexical");
    await expect(conflict).toContainText("kept apart from what was read directly");
    await expect(conflict).toContainText("Confidence");
  });

  test("the policy tables decide which controls exist, not the interface", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.locator('.card[data-req="BG-07"]').waitFor({ timeout: 90_000 });

    const rights = page.locator('.card[data-req="BG-07"]');
    await expect(rights).toContainText("Only production can resolve this");
    await expect(rights.locator("button.decide")).toHaveCount(0);

    await page.selectOption("#role", "production_coordinator");
    // Production may confirm and reject. Nobody, including production, may
    // accept a missing release away.
    await expect(rights.locator("button.decide")).toHaveCount(2);
    await expect(rights.locator('button[data-action="accept_exception"]')).toHaveCount(0);
    await expect(rights).toContainText("No role is offered a way to accept this away");
  });

  test("the run stops for the 1st AD and resumes across the pause", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.locator(".pause").waitFor({ timeout: 90_000 });

    // Signed in as the supervisor there is no approve control at all.
    await expect(page.locator(".notyou")).toContainText("Only the 1st AD can approve this");
    await expect(page.locator("#bYes")).toHaveCount(0);

    // The walk hands over the chair that can answer, and then stops.
    await page.locator("#go").click();
    await expect(page.locator("#role")).toHaveValue("first_ad");
    await expect(page.locator("#bYes")).toBeVisible();

    await page.locator("#bYes").click();
    await expect(page.locator('.step[data-step="s2"]')).toHaveClass(/done/, { timeout: 90_000 });
  });

  test("the whole walk reaches a sealed turnover", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.locator("#go").waitFor({ timeout: 90_000 });

    // Six moves. Where a human decides, press the control a human would press.
    for (let move = 0; move < 12; move += 1) {
      const label = await page.locator("#go").textContent();
      if (label?.includes("complete")) break;

      await page.locator("#go").click();
      await page.waitForTimeout(1_500);

      const approve = page.locator("#bYes");
      if (await approve.count()) {
        await approve.click();
        await page.waitForTimeout(2_500);
        continue;
      }
      const accept = page.locator('.card.linked button[data-action="accept_exception"]');
      if (await accept.count()) {
        await accept.first().click();
        await page.waitForTimeout(2_500);
      }
      await page.waitForTimeout(2_000);
    }

    await expect(page.locator("#go")).toHaveText(/complete/, { timeout: 60_000 });
    await expect(page.locator("#vhead")).toHaveText("This scene is ready to hand to editorial.");
    await expect(page.locator("#turnbox")).toContainText("Published and sealed");
    await expect(page.locator(".step.done")).toHaveCount(6);
  });
});
