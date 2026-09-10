// Test driver only. Observe the legacy page's existing guards and saved state.
export async function waitForIdle(page) {
  await page.waitForFunction(() => window.BUSY === false);
}

export async function waitForApproval(page, isWrap) {
  await page.waitForFunction((wrap) => {
    if (window.BUSY !== false || window.PENDING) return false;
    if (!wrap) return window.PICKUP_APPROVED === true;
    // Wrap approval chains another request to publish the turnover. An idle
    // approval response alone must not advance the test into the disabled Next.
    return window.STATE?.wrap_approved === true
      && document.getElementById("turnbox")?.textContent.includes("Published and sealed");
  }, isWrap);
}

export async function walkToTurnover(page) {
  for (let move = 0; move < 12; move += 1) {
    await waitForIdle(page);
    if ((await page.locator("#go").textContent())?.includes("complete")) return;
    await page.locator("#go").click();
    await waitForIdle(page);

    const approve = page.locator("#bYes");
    if (await approve.count()) {
      const isWrap = await page.evaluate(() => window.PENDING?.reason?.kind === "wrap");
      await approve.click();
      await waitForApproval(page, isWrap);
      continue;
    }
    const accept = page.locator('.card.linked button[data-action="accept_exception"]');
    if (await accept.count()) {
      await accept.first().click();
      await waitForIdle(page);
    }
  }
  throw new Error("The governed walkthrough did not complete within twelve moves");
}
