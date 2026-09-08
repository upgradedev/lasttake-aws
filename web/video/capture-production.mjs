// Drives the live URL through the shoot day and records it, one scene per
// narration beat, holding each scene for exactly as long as its measured audio.
//
// Adapted from the kit's archon-datahub capture. The pristine copy is at
// video/upstream/archon-datahub/capture-production.mjs; diff against it to see
// what changed. What changed is the journey, the origin, and that the two
// DataHub proof run ids are optional here because this project has no
// equivalent of them.
//
// The holds come from narration/timing.json, which generate-narration.py wrote
// after measuring each mp3 with ffprobe. So the picture cannot drift from the
// voice: a scene is on screen for the length of its own sentence plus the tail,
// and changing one line of narration re-times one scene and nothing else.

import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";

const root = process.env.ARCHON_VIDEO_ROOT;
const releaseSha = process.env.ARCHON_RELEASE_SHA;
const appOrigin = process.env.LASTTAKE_URL
  ?? "https://1p6s28nyf0.execute-api.eu-west-1.amazonaws.com";
if (!root || !/^[a-f0-9]{40}$/u.test(releaseSha ?? "")) {
  throw new Error("The exact video root and release SHA are required.");
}

const captureDir = path.join(root, "capture");
mkdirSync(captureDir, { recursive: false });
const timing = JSON.parse(
  readFileSync(path.join(root, "narration", "timing.json"), "utf8"),
);
const holds = Object.fromEntries(
  timing.scenes.map((scene) => [scene.id, Number(scene.holdSeconds) * 1000]),
);
const expectedScenes = ["hook", "surface", "trigger", "live", "sponsor", "evidence", "close"];
if (JSON.stringify(timing.scenes.map((scene) => scene.id)) !== JSON.stringify(expectedScenes)) {
  throw new Error("The narration and the production journey scene order differ.");
}

const browser = await chromium.launch({ args: ["--force-device-scale-factor=1"] });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  recordVideo: { dir: path.join(captureDir, "raw"), size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();
const video = page.video();
if (!video) throw new Error("Playwright did not create a video recorder.");

const errors = [];
const onOwnedOrigin = () => page.url().startsWith(appOrigin);
page.on("pageerror", (error) => {
  if (onOwnedOrigin()) errors.push(`page:${error.name}`);
});
page.on("console", (message) => {
  if (onOwnedOrigin() && message.type() === "error") errors.push("console:error");
});

const captureStarted = Date.now();
const appUrl = `${appOrigin}/?release=${releaseSha}`;
await page.goto(appUrl, { waitUntil: "networkidle", timeout: 60_000 });
// The lined script paints from the package alone, before any check has run.
await page.locator(".beat").first().waitFor({ timeout: 60_000 });
const timelineStarted = Date.now();

async function holdScene(id, action) {
  const started = Date.now();
  await action();
  await page.waitForTimeout(Math.max(0, holds[id] - (Date.now() - started)));
}

// The page must never print a clearance. If it does, the recording stops here
// rather than producing a polished film of the product breaking its own rule.
const forbidden = ["CLEAR TO SHOOT", "rules verified", "Multi-Agent Evaluation"];
const body = await page.locator("body").innerText();
for (const phrase of forbidden) {
  if (body.toLowerCase().includes(phrase.toLowerCase())) {
    throw new Error(`The page prints ${phrase}, which this product does not say.`);
  }
}

await holdScene("hook", async () => {
  await page.evaluate(() => window.scrollTo({ top: 0 }));
});

await holdScene("surface", async () => {
  // Down the lined script, slowly, so the beats and their slates read.
  await page.locator("#paneLeft").evaluate((pane) => {
    pane.scrollTo({ top: 900, behavior: "smooth" });
  });
  await page.waitForTimeout(1_500);
  await page.locator('.take[data-take="T-013"]').first().click();
  await page.locator("#drawer.on").waitFor({ timeout: 15_000 });
  await page.waitForTimeout(2_500);
  await page.locator("#scrim").click();
});

await holdScene("trigger", async () => {
  // The count, and the exceptions it is made of.
  await page.locator("#tally").waitFor({ timeout: 60_000 });
  await page.locator("#paneRight").evaluate((pane) => {
    pane.scrollTo({ top: 0, behavior: "smooth" });
  });
  await page.waitForTimeout(1_500);
  await page.locator('.card[data-req="B-17"]').click();
  await page.waitForTimeout(1_500);
});

await holdScene("live", async () => {
  // The pause. The walk moves the visitor into the chair that can answer, and
  // stops. Nothing here approves on the viewer's behalf.
  await page.locator("#go").click();
  await page.locator("#bYes").waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2_000);
  await page.locator("#bYes").click();
  await page.waitForTimeout(3_000);
});

await holdScene("sponsor", async () => {
  // The process boundary, and the query object storage cannot answer.
  await page.locator(".proof").scrollIntoViewIfNeeded();
  await page.waitForTimeout(1_500);
  await page.locator("#paneRight").evaluate((pane) => {
    pane.scrollTo({ top: pane.scrollHeight, behavior: "smooth" });
  });
  await page.locator(".xrun").waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2_000);
});

await holdScene("evidence", async () => {
  // Sources and digests, under the finding they belong to.
  await page.locator("#paneRight").evaluate((pane) => {
    pane.scrollTo({ top: 0, behavior: "smooth" });
  });
  await page.waitForTimeout(1_000);
  await page.locator(".card details.ev summary").first().click();
  await page.waitForTimeout(2_500);
});

await holdScene("close", async () => {
  await page.goto(appUrl, { waitUntil: "networkidle", timeout: 60_000 });
  await page.locator(".beat").first().waitFor({ timeout: 60_000 });
});

await context.close();
await browser.close();
const rawPath = await video.path();
const finalPath = path.join(captureDir, "production.webm");
renameSync(rawPath, finalPath);
const bytes = readFileSync(finalPath);
const receipt = {
  schemaVersion: "archon.submission-video-capture/v1",
  releaseSha,
  appOrigin,
  sceneCount: expectedScenes.length,
  trimLeadSeconds: Math.max(0, (timelineStarted - captureStarted) / 1000),
  timelineSeconds: Number(timing.totalSeconds),
  pageErrors: errors,
  bytes: bytes.length,
  sha256: createHash("sha256").update(bytes).digest("hex"),
};
writeFileSync(
  path.join(captureDir, "capture-receipt.json"),
  `${JSON.stringify(receipt, null, 2)}\n`,
);
if (errors.length !== 0) {
  throw new Error(`The production journey emitted ${errors.length} browser errors.`);
}
console.log(JSON.stringify(receipt));
