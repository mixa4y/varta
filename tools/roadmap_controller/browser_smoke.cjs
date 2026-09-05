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
      progressPanels: document.querySelectorAll(".stage-progress").length,
      liveOverview: document.getElementById("live-execution") !== null,
      livePercent: document.getElementById("live-progress-percent")?.textContent.trim(),
      enabledStarts: starts.filter(button => !button.disabled).map(button => button.dataset.stageId),
      disabledStarts: starts.filter(button => button.disabled).length,
      gitStarts: gitStarts.length,
      enabledGitStarts: gitStarts.filter(button => !button.disabled).map(button => button.dataset.stageId),
      packageSummaries: [...document.querySelectorAll('article[data-stage-id]')].map(card => ({
        id: card.dataset.stageId,
        summary: card.querySelector('summary .status')?.textContent.trim(),
        tone: card.dataset.status,
        runStatus: card.querySelector('.live-controls .run-badge')?.dataset.runStatus,
        gitStatus: card.querySelector('.live-controls .git-badge')?.dataset.gitStatus,
        canStart: !card.querySelector('.start-stage')?.disabled,
      })),
      executionStats: [...document.querySelectorAll('#execution-stats .stat b')]
        .map(element => element.textContent.trim()),
      pinnedRegions: [...document.querySelectorAll("body *")]
        .filter(element => ["fixed", "sticky"].includes(getComputedStyle(element).position))
        .map(element => element.id || element.className || element.tagName),
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  });
  await page.click("#expand-all");
  snapshot.openDetails = await page.locator("details[open]").count();
  snapshot.expandedToggle = await page.locator("article[data-stage-id] summary .id").first()
    .evaluate(element => getComputedStyle(element, "::before").content);
  await page.click("#collapse-all");
  snapshot.closedDetails = await page.locator("details[open]").count();
  snapshot.collapsedToggle = await page.locator("article[data-stage-id] summary .id").first()
    .evaluate(element => getComputedStyle(element, "::before").content);
  await page.click("#expand-all");
  if (exerciseStart) {
    let interceptedStarts = 0;
    const stageId = snapshot.enabledStarts[0];
    if (stageId) {
      await page.route(`**/api/v1/stages/${stageId}/start`, async route => {
        interceptedStarts += 1;
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ stageId, run: { runStatus: "starting" } }),
        });
      });
      page.once("dialog", dialog => dialog.accept());
      const response = page.waitForResponse(candidate => (
        new URL(candidate.url()).pathname === `/api/v1/stages/${stageId}/start`
        && candidate.request().method() === "POST"
      ));
      await page.click(`article[data-stage-id="${stageId}"] .start-stage`);
      await response;
    }
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
      if (result.snapshot.progressPanels !== 40) throw new Error("Expected 40 progress panels");
      if (!result.snapshot.liveOverview) throw new Error("Expected persistent live overview");
      const percent = Number.parseInt(result.snapshot.livePercent, 10);
      if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
        throw new Error(`Invalid live progress: ${result.snapshot.livePercent}`);
      }
      if (result.snapshot.enabledStarts.length > 1) {
        throw new Error(`More than one enabled stage: ${result.snapshot.enabledStarts.join(",")}`);
      }
      if (result.snapshot.disabledStarts !== 20 - result.snapshot.enabledStarts.length) {
        throw new Error("Start-button gate count is inconsistent");
      }
      if (result.snapshot.gitStarts !== 20) throw new Error("Expected 20 Git checkpoint buttons");
      if (result.snapshot.enabledGitStarts.length > 1) {
        throw new Error(`More than one enabled Git checkpoint: ${result.snapshot.enabledGitStarts.join(",")}`);
      }
      const expectedSummary = item => {
        if (item.gitStatus === "synced") return "DONE";
        if (["starting", "running"].includes(item.gitStatus)) return "GIT RUNNING";
        if (item.gitStatus === "waiting") return "GIT WAITING";
        if (item.gitStatus === "failed") return "GIT FAILED";
        if (item.gitStatus === "blocked") return "GIT BLOCKED";
        if (item.gitStatus === "interrupted") return "GIT STOPPED";
        if (item.gitStatus === "needs_review") return "GIT REVIEW";
        if (item.runStatus === "completed") {
          return item.gitStatus === "awaiting_approval" ? "GIT READY" : "TECH PASS";
        }
        if (["starting", "running"].includes(item.runStatus)) return "RUNNING";
        if (item.runStatus === "waiting") return "WAITING";
        if (item.runStatus === "failed") return "FAILED";
        if (item.runStatus === "blocked") return "BLOCKED";
        if (item.runStatus === "interrupted") return "STOPPED";
        if (item.runStatus === "needs_review") return "REVIEW";
        return item.canStart ? "READY" : "WAITING";
      };
      const summaryMismatches = result.snapshot.packageSummaries
        .filter(item => item.summary !== expectedSummary(item))
        .map(item => `${item.id}:${item.summary}`);
      if (summaryMismatches.length) {
        throw new Error(`Package summaries do not match runtime: ${summaryMismatches.join(",")}`);
      }
      if (result.snapshot.executionStats.some(value => !/^\d+$/.test(value))) {
        throw new Error(`Execution stats are not live counts: ${result.snapshot.executionStats.join(",")}`);
      }
      if (result.snapshot.pinnedRegions.length) {
        throw new Error(`Unexpected fixed/sticky regions: ${result.snapshot.pinnedRegions.join(",")}`);
      }
      if (result.snapshot.openDetails !== 20) throw new Error("Expected 20 expanded C/P packages");
      if (result.snapshot.closedDetails !== 0) throw new Error("Collapse-all did not close every card");
      if (result.snapshot.expandedToggle !== '"−"') throw new Error("Expanded card must show minus");
      if (result.snapshot.collapsedToggle !== '"+"') throw new Error("Collapsed card must show plus");
      if (result.snapshot.overflow) throw new Error("Horizontal overflow detected");
      if (result.consoleErrors.length) throw new Error(`Console errors: ${result.consoleErrors}`);
      if (result.pageErrors.length) throw new Error(`Page errors: ${result.pageErrors}`);
      if (result.externalRequests.length) {
        throw new Error(`External requests: ${result.externalRequests.join(", ")}`);
      }
    }
    const expectedStarts = desktop.snapshot.enabledStarts.length ? 1 : 0;
    if (desktop.snapshot.interceptedStarts !== expectedStarts) {
      throw new Error("Start button did not issue exactly one intercepted package request");
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
