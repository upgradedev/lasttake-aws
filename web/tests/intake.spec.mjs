// LT-01 and LT-02, walked in a browser against the deployed URL.
//
// The completion rule this is written against: an item is complete only when the
// intended user can execute it on the declared environment, the outcome persists
// and can be read back, and negative cases fail at the intended boundary. So
// every test here goes browser -> API -> persistent state -> visible result, and
// the reload is not decoration: it is the assertion.
//
// Reload used to be the thing that broke this. Every page load minted a new run
// id, so a refresh discarded whatever had been ingested and re-ran the checkpoint
// against the untouched corpus. The one thing this product is for, watching a
// supplied document change the findings, was unobservable to anyone who pressed
// refresh.
//
//   npx playwright test --config web/playwright.config.mjs

import { expect, test } from "@playwright/test";

const URL = process.env.LASTTAKE_URL
  ?? "https://1p6s28nyf0.execute-api.eu-west-1.amazonaws.com/";

/** A pickup take against B-17, the one beat the corpus leaves uncovered. */
function aTake(overrides = {}) {
  return JSON.stringify({
    take_id: "T-900",
    shot_id: "S-42-PICKUP",
    beat_ids: ["B-17"],
    slate: "42L/1",
    camera_roll: "A007",
    sound_roll: "SR07",
    timecode_in: "23:04:00:00",
    timecode_out: "23:04:41:00",
    lens_mm: 50,
    media_id: "A007R2G01",
    preferred: true,
    usable: true,
    note: "Pickup on the reaction. Clean single, held.",
    visible_people: ["DELPHINE"],
    ...overrides,
  }, null, 2);
}

async function openFresh(page) {
  await page.goto(URL, { waitUntil: "networkidle" });
  // Start from a run of our own, so a previous test's shoot day is never the
  // thing under test. This is also the control that proves the reset works.
  await page.locator("#bReset").click();
  await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });
  return page.evaluate(() => window.RUN ?? JSON.parse(localStorage.getItem("lasttake.run")).run_id);
}

async function submit(page, kind, text) {
  await page.selectOption("#ingestKind", kind);
  await page.locator("#ingestDoc").fill(text);
  await page.locator("#bIngest").click();
  await expect(page.locator("#ingestOut .shape")).toBeVisible({ timeout: 90_000 });
}

test.describe("LT-01, a document a person supplied", () => {
  test.describe.configure({ mode: "serial", timeout: 300_000 });

  test("an invalid document names the problem, keeps the form and writes nothing", async ({ page }) => {
    await openFresh(page);

    const before = await page.locator(".take").count();
    const typed = aTake({ slate: undefined });
    await submit(page, "take", typed);

    const out = page.locator("#ingestOut .shape");
    await expect(out).toHaveClass(/bad/);
    await expect(out).toContainText("missing: slate");

    // The form still holds what the person typed. Losing it on a validation
    // error is how somebody stops using a form.
    await expect(page.locator("#ingestDoc")).toHaveValue(typed);

    // And nothing was written. A refusal that half-applies is worse than one
    // that fails, because the next read is neither the old state nor the new.
    await expect(page.locator(".take")).toHaveCount(before);
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });
    await expect(page.locator(".take")).toHaveCount(before);
  });

  test("malformed JSON is refused by the page before it reaches the API", async ({ page }) => {
    await openFresh(page);
    await submit(page, "take", "{ this is not json");
    await expect(page.locator("#ingestOut .shape")).toHaveClass(/bad/);
    await expect(page.locator("#ingestOut .shape")).toContainText("not valid JSON");
  });

  test("a valid take changes the findings, and the change survives a reload", async ({ page }) => {
    const run = await openFresh(page);

    // Before: B-17 has nothing shot against it, and the count says so.
    await expect(page.locator('.beat[data-beat="B-17"]')).toHaveClass(/s-nocov/);
    await expect(page.locator('.beat[data-beat="B-17"]')).toContainText(
      "Nothing was shot against this beat",
    );
    await expect(page.locator("#basisline")).toContainText("rest on nothing");

    await submit(page, "take", aTake());
    const out = page.locator("#ingestOut .shape");
    await expect(out).toHaveClass(/good/);
    // All four checks read the takes document, so all four rerun. Derived from
    // which digests moved, not from a table asserting it.
    await expect(out).toContainText("coverage");
    await expect(out).toContainText("continuity");

    await expect(page.locator('.beat[data-beat="B-17"]')).toHaveClass(/s-covered/);
    await expect(page.locator('.take[data-take="T-900"]')).toBeVisible();

    // The reload. This is the assertion, not the setup.
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });

    // Same run, read back from the record rather than recomputed.
    const after = await page.evaluate(
      () => JSON.parse(localStorage.getItem("lasttake.run")).run_id,
    );
    expect(after).toBe(run);
    await expect(page.locator(".banner")).toContainText("Resumed run");

    // And the document a person supplied is still the evidence on the page.
    await expect(page.locator('.take[data-take="T-900"]')).toBeVisible();
    await expect(page.locator('.beat[data-beat="B-17"]')).toHaveClass(/s-covered/);
    await expect(page.locator('.beat[data-beat="B-17"]')).toContainText(
      "corroborated by the interpreter",
    );
  });

  test("the same document twice does not write it twice", async ({ page }) => {
    await openFresh(page);
    await submit(page, "take", aTake());
    await expect(page.locator("#ingestOut .shape")).toHaveClass(/good/);
    // Count only once the take is actually on the script. The confirmation and
    // the refreshed script now land together, and this makes the test say so
    // rather than depend on it.
    await expect(page.locator('.take[data-take="T-900"]')).toBeVisible();
    const once = await page.locator(".take").count();

    await submit(page, "take", aTake());
    await expect(page.locator("#ingestOut .shape")).toHaveClass(/bad/);
    await expect(page.locator("#ingestOut .shape")).toContainText("already in this scene package");
    await expect(page.locator(".take")).toHaveCount(once);
  });

  test("a fresh shoot day is a different run and does not inherit the old one", async ({ page }) => {
    const first = await openFresh(page);
    await submit(page, "take", aTake());
    await expect(page.locator('.take[data-take="T-900"]')).toBeVisible();

    await page.locator("#bReset").click();
    await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });

    const second = await page.evaluate(
      () => JSON.parse(localStorage.getItem("lasttake.run")).run_id,
    );
    expect(second).not.toBe(first);
    await expect(page.locator('.take[data-take="T-900"]')).toHaveCount(0);
    await expect(page.locator('.beat[data-beat="B-17"]')).toHaveClass(/s-nocov/);
  });
});

test.describe("LT-02, an approval does not survive the evidence it was about", () => {
  test.describe.configure({ mode: "serial", timeout: 300_000 });

  test("changed evidence withdraws the approval and demands a new one", async ({ page }) => {
    await openFresh(page);

    // A supervisor accepts the continuity conflict as intentional.
    await page.selectOption("#role", "script_supervisor");
    const conflict = page.locator('.card[data-req="CR-01"]');
    await expect(conflict).toBeVisible();
    await conflict.locator('button[data-action="accept_exception"]').click();
    await expect(conflict.locator(".decided")).toContainText("accept exception", {
      timeout: 90_000,
    });

    // Then a take arrives that changes what the continuity check reads.
    await submit(page, "take", aTake());
    const out = page.locator("#ingestOut .shape");
    await expect(out).toHaveClass(/good/);

    // The page says which approval no longer applies, and why.
    await expect(out).toContainText("no longer applies");
    await expect(out).toContainText("read again since");

    // The card stops reading "accepted" and says what happened instead. Silently
    // dropping the approval would be its own confusion: a supervisor needs to
    // know an approval existed and why it stopped counting.
    await expect(conflict.locator(".decided")).toHaveCount(0);
    await expect(conflict.locator(".withdrawn")).toContainText("no longer applies");
    await expect(conflict.locator(".withdrawn")).toContainText("read again since");

    // And the control to take a new decision is back, because somebody has to.
    await expect(
      conflict.locator('button[data-action="accept_exception"]'),
    ).toBeVisible();

    // It survives a reload, because the withdrawal is a property of the record
    // and not of this tab.
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });
    const reloaded = page.locator('.card[data-req="CR-01"]');
    await expect(reloaded.locator(".decided")).toHaveCount(0);
    await expect(reloaded.locator(".withdrawn")).toBeVisible();

    // A fresh, explicit approval closes it again, and this one is about the
    // reading that exists now.
    await reloaded.locator('button[data-action="accept_exception"]').click();
    await expect(reloaded.locator(".decided")).toContainText("accept exception", {
      timeout: 90_000,
    });
    await expect(reloaded.locator(".withdrawn")).toHaveCount(0);
  });

  test("a decision survives a reload and the gate reads it back", async ({ page }) => {
    await openFresh(page);

    await page.selectOption("#role", "dit");
    const media = page.locator('.card[data-req="T-013"]');
    await media.locator('button[data-action="accept_exception"]').click();
    await expect(media.locator(".decided")).toContainText("accept exception", {
      timeout: 90_000,
    });

    await page.reload({ waitUntil: "networkidle" });
    await expect(page.locator("#tally")).toContainText("34", { timeout: 90_000 });

    // The decision is on the record, with who took it, read back from the
    // server rather than replayed from this browser.
    const after = page.locator('.card[data-req="T-013"]');
    await expect(after.locator(".decided")).toContainText("dit");
    await expect(after.locator(".decided")).toContainText("still travels on the turnover");
  });
});
