// Drives the live URL through the shoot day and records it, one scene per
// narration beat, holding each scene for exactly as long as its measured audio.
//
// Adapted from the kit's archon-datahub capture. The pristine copy is at
// video/upstream/archon-datahub/capture-production.mjs; diff against it to see
// what changed. The current journey, origin, namespaces and optional proof bindings
// are LastTake-specific. Narration and release verification remain owner-gated.
//
// The holds come from narration/timing.json, which generate-narration.py wrote
// after measuring each mp3 with ffprobe. So the picture cannot drift from the
// voice: a scene is on screen for the length of its own sentence plus the tail,
// and changing one line of narration re-times one scene and nothing else.

import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";

const spec = JSON.parse(readFileSync(new URL("../../video/narration.json", import.meta.url), "utf8"));
if (spec.recording_status !== "READY_OWNER_VERIFIED") {
  throw new Error("NOT_CONFIGURED: owner must verify release, narration, capture and timing.");
}
const root = process.env.LASTTAKE_VIDEO_ROOT;
const releaseSha = process.env.LASTTAKE_RELEASE_SHA;
const appOrigin = process.env.LASTTAKE_URL
  ?? "https://d3kf6hquzlli8g.cloudfront.net";
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
const release = await (await context.request.get(appOrigin + "/release.json")).json();
if (release.commit !== releaseSha) throw new Error("Frontend release mismatch before recording");
await page.goto(appUrl, { waitUntil: "networkidle", timeout: 60_000 });
await page.getByRole("button", { name: "New shoot-day run", exact: true }).click();
await page.getByRole("button", { name: "Run wrap checkpoint" }).waitFor();
const timelineStarted = Date.now();

async function holdScene(id, action) {
  const started = Date.now();
  await action();
  await page.waitForTimeout(Math.max(0, holds[id] - (Date.now() - started)));
}

await holdScene("hook", async () => {
  await page.getByRole("heading", { name: "Workspace", exact: true }).scrollIntoViewIfNeeded();
});
await holdScene("surface", async () => {
  await page.locator(".take summary").first().click();
});
await holdScene("trigger", async () => {
  await page.getByRole("button", { name: "Run wrap checkpoint" }).click();
  await page.getByText(/Of 34 required beats/).first().waitFor({ timeout: 60_000 });
});
await holdScene("live", async () => {
  await page.getByLabel("Demo role").selectOption("first_ad");
  await page.reload();
  await page.getByRole("button", { name: "Decline pickup" }).waitFor({ timeout: 30_000 });
  await page.getByRole("button", { name: "Decline pickup" }).click();
  await page.getByText(/did not approve a pickup/).waitFor();
});
await holdScene("sponsor", async () => {
  await page.getByText("Run details & execution labels").click();
  await page.getByText("Strands Agents SDK", { exact: true }).scrollIntoViewIfNeeded();
});
await holdScene("evidence", async () => {
  await page.getByRole("navigation").getByRole("link", { name: "History", exact: true }).click();
  await page.getByRole("button", { name: "Prepare receipt" }).click();
  await page.getByRole("button", { name: "Download evidence summary" }).waitFor();
});
await holdScene("close", async () => {
  await page.getByRole("navigation").getByRole("link", { name: "Workspace", exact: true }).click();
  await page.getByRole("button", { name: "Open guided demo" }).click();
  await page.getByRole("button", { name: "Add take or release" }).click();
  await page.getByRole("button", { name: "Try refused date" }).click();
});
const after = await (await context.request.get(appOrigin + "/release.json")).json();
if (after.commit !== releaseSha) throw new Error("Frontend release changed during recording");

await context.close();
await browser.close();
const rawPath = await video.path();
const finalPath = path.join(captureDir, "production.webm");
renameSync(rawPath, finalPath);
const bytes = readFileSync(finalPath);
const receipt = {
  schemaVersion: "lasttake.submission-video-capture/v1",
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
