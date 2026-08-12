"use strict";

const { chromium } = require("playwright");

async function inspectPage(browser, url, viewport, screenshotPath, exerciseStart = false) {
  const page = await browser.newPage({ viewportSize: viewport });
  const consoleErrors = [];
  const pageErrors = [];
  const externalRequests = [];
  const allRequests = [];
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("request", request => {
    allRequests.push(request.url());
    const target = new URL(request.url());
    if (!(["127.0.0.1", "localhost"].includes(target.hostname))) {
      externalRequests.push(request.url());
    }
  });

  await page.goto(url, { waitUntil: "networkidle" });
  try {
    await page.waitForFunction(
      () => document.querySelectorAll(".live-controls").length === 20,
      null,
      { timeout: 30000 },
    );
  } catch (error) {
    const count = await page.locator(".live-controls").count();
    throw new Error(
      `Live controls timeout; count=${count}; console=${consoleErrors.join(" | ")}; `
      + `page=${pageErrors.join(" | ")}; requests=${allRequests.join(" | ")}; `
      + `state=${JSON.stringify(await page.evaluate(() => ({
        protocol: location.protocol,
        token: document.querySelector('meta[name="varta-session-token"]')?.content,
        badge: document.getElementById("connection-badge")?.textContent,
        message: document.getElementById("controller-message")?.textContent,
        refreshType: typeof refreshRoadmap,
      })))}; original=${error.message}`,
    );
  }
  const snapshot = await page.evaluate(() => {
    const starts = [...document.querySelectorAll(".start-stage")];
    const gitStarts = [...document.querySelectorAll(".start-git")];
    return {
      title: document.title,
      badge: document.getElementById("connection-badge").textContent.trim(),
      stageCards: document.querySelectorAll("article[data-stage-id]").length,
      liveControls: document.querySelectorAll(".live-controls").length,
      enabledStarts: starts.filter(button => !button.disabled).map(button => button.dataset.stageId),
      disabledStarts: starts.filter(button => button.disabled).length,
      gitStarts: gitStarts.length,
      enabledGitStarts: gitStarts.filter(button => !button.disabled).map(button => button.dataset.stageId),
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  });
  await page.click("#expand-all");
  snapshot.openDetails = await page.locator("details[open]").count();
  if (exerciseStart) {
    let interceptedStarts = 0;
    await page.route("**/api/v1/stages/C01/start", async route => {
      interceptedStarts += 1;
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ stageId: "C01", run: { runStatus: "starting" } }),
      });
    });
    page.once("dialog", dialog => dialog.accept());
    await page.click('article[data-stage-id="C01"] .start-stage');
    await page.waitForFunction(
      () => document.getElementById("copy-result").textContent.includes("Task C01"),
    );
    snapshot.interceptedStarts = interceptedStarts;
  }
  if (screenshotPath) {
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }
  await page.close();
  return { snapshot, consoleErrors, pageErrors, externalRequests };
}

async function main() {
  const url = process.argv[2] || "http://127.0.0.1:8766/";
  const executablePath = process.argv[3];
  if (!executablePath) throw new Error("Pass the Microsoft Edge executable path");
  const screenshotRoot = process.argv[4] || null;
  const browser = await chromium.launch({ executablePath, headless: true });
  try {
    const desktop = await inspectPage(
      browser,
      url,
      { width: 1280, height: 900 },
      screenshotRoot ? `${screenshotRoot}-desktop.png` : null,
      true,
    );
    const mobile = await inspectPage(
      browser,
      url,
      { width: 390, height: 844 },
      screenshotRoot ? `${screenshotRoot}-mobile.png` : null,
    );
    for (const result of [desktop, mobile]) {
      if (result.snapshot.badge !== "CODEX READY") throw new Error("Codex badge is not ready");
      if (result.snapshot.stageCards !== 20) throw new Error("Expected 20 stage cards");
      if (result.snapshot.liveControls !== 20) throw new Error("Expected 20 live controls");
      if (result.snapshot.enabledStarts.join(",") !== "C01") {
        throw new Error(`Unexpected enabled stages: ${result.snapshot.enabledStarts.join(",")}`);
      }
      if (result.snapshot.disabledStarts !== 19) throw new Error("Expected 19 gated starts");
      if (result.snapshot.gitStarts !== 20) throw new Error("Expected 20 Git checkpoint buttons");
      if (result.snapshot.enabledGitStarts.length !== 0) {
        throw new Error(`Unexpected enabled Git checkpoints: ${result.snapshot.enabledGitStarts.join(",")}`);
      }
      if (result.snapshot.openDetails !== 16) throw new Error("Expected 16 expanded core stages");
      if (result.snapshot.overflow) throw new Error("Horizontal overflow detected");
      if (result.consoleErrors.length) throw new Error(`Console errors: ${result.consoleErrors}`);
      if (result.pageErrors.length) throw new Error(`Page errors: ${result.pageErrors}`);
      if (result.externalRequests.length) {
        throw new Error(`External requests: ${result.externalRequests.join(", ")}`);
      }
    }
    if (desktop.snapshot.interceptedStarts !== 1) {
      throw new Error("Start button did not issue exactly one C01 request");
    }
    process.stdout.write(`${JSON.stringify({ desktop: desktop.snapshot, mobile: mobile.snapshot })}\n`);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
