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
      () => {
        const stageCards = document.querySelectorAll("article[data-stage-id]").length;
        return stageCards === 24
          && document.querySelectorAll(".live-controls").length === stageCards
          && document.querySelectorAll("summary .model-badge").length === stageCards
          && document.querySelectorAll(".rerun-config").length === stageCards
          && document.querySelectorAll(".rerun-stage").length === stageCards
          && document.querySelectorAll(".start-review").length === stageCards
          && document.querySelectorAll(".rerun-model").length === stageCards
          && document.querySelectorAll(".rerun-effort").length === stageCards;
      },
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
        badge: document.getElementById("connection-badge")?.textContent,
        message: document.getElementById("controller-message")?.textContent,
        refreshType: typeof refreshRoadmap,
      })))}; original=${error.message}`,
    );
  }
  const snapshot = await page.evaluate(() => {
    const starts = [...document.querySelectorAll(".start-stage")];
    const gitStarts = [...document.querySelectorAll(".start-git")];
    const reviews = [...document.querySelectorAll(".start-review")];
    const reruns = [...document.querySelectorAll(".rerun-stage")];
    return {
      title: document.title,
      badge: document.getElementById("connection-badge").textContent.trim(),
      stageCards: document.querySelectorAll("article[data-stage-id]").length,
      liveControls: document.querySelectorAll(".live-controls").length,
      modelBadges: document.querySelectorAll("summary .model-badge").length,
      rerunControls: document.querySelectorAll(".rerun-config").length,
      rerunButtons: reruns.length,
      rerunModels: document.querySelectorAll(".rerun-model").length,
      rerunEfforts: document.querySelectorAll(".rerun-effort").length,
      progressPanels: document.querySelectorAll(".stage-progress").length,
      liveOverview: document.getElementById("live-execution") !== null,
      nextAction: typeof latestSnapshot === "object" ? latestSnapshot?.nextAction : null,
      liveStageId: document.getElementById("live-stage-id")?.textContent.trim(),
      liveStageTitle: document.getElementById("live-stage-title")?.textContent.trim(),
      liveRunBadge: document.getElementById("live-run-badge")?.textContent.trim(),
      livePercent: document.getElementById("live-progress-percent")?.textContent.trim(),
      footerMessage: document.getElementById("roadmap-footer-message")?.textContent.trim(),
      enabledStarts: starts.filter(button => !button.disabled).map(button => button.dataset.stageId),
      disabledStarts: starts.filter(button => button.disabled).length,
      gitStarts: gitStarts.length,
      enabledGitStarts: gitStarts.filter(button => !button.disabled).map(button => button.dataset.stageId),
      reviewStarts: reviews.length,
      enabledReviews: reviews.filter(button => !button.disabled).map(button => button.dataset.stageId),
      enabledReruns: reruns.filter(button => !button.disabled).map(button => button.dataset.stageId),
      packageSummaries: [...document.querySelectorAll('article[data-stage-id]')].map(card => {
        const runtimeStage = latestSnapshot?.stages?.find(stage => stage.id === card.dataset.stageId);
        const modelBadge = card.querySelector('.model-badge');
        return {
          id: card.dataset.stageId,
          summary: card.querySelector('summary .status')?.textContent.trim(),
          tone: card.dataset.status,
          runStatus: card.querySelector('.live-controls .run-badge')?.dataset.runStatus,
          gitStatus: card.querySelector('.live-controls .git-badge')?.dataset.gitStatus,
          canStart: !card.querySelector('.start-stage')?.disabled,
          blockedBy: (card.dataset.blockedBy || "").split(",").filter(Boolean),
          model: modelBadge?.dataset.model || "",
          effort: modelBadge?.dataset.effort || "",
          modelSource: modelBadge?.dataset.source || "",
          modelLabel: modelBadge?.textContent.trim() || "",
          runtimeExecution: runtimeStage?.execution || null,
          runtimeCanRerun: Boolean(runtimeStage?.canRerun),
          rerunHidden: card.querySelector('.rerun-config')?.hidden,
          rerunDisabled: card.querySelector('.rerun-stage')?.disabled,
          rerunModel: card.querySelector('.rerun-model')?.value || "",
          rerunEffort: card.querySelector('.rerun-effort')?.value || "",
          rerunModelOptions: card.querySelector('.rerun-model')?.options.length || 0,
          rerunModelValues: [...(card.querySelector('.rerun-model')?.options || [])]
            .map(option => option.value),
          rerunEffortOptions: card.querySelector('.rerun-effort')?.options.length || 0,
        };
      }),
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
    let interceptedReruns = 0;
    let rerunPayload = null;
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
    const rerunStageId = snapshot.enabledReruns[0];
    if (rerunStageId) {
      await page.route(`**/api/v1/stages/${rerunStageId}/rerun`, async route => {
        interceptedReruns += 1;
        rerunPayload = route.request().postDataJSON();
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ rerunStageId, run: { runStatus: "starting" } }),
        });
      });
      page.once("dialog", dialog => dialog.accept());
      const rerunResponse = page.waitForResponse(candidate => (
        new URL(candidate.url()).pathname === `/api/v1/stages/${rerunStageId}/rerun`
        && candidate.request().method() === "POST"
      ));
      await page.click(`article[data-stage-id="${rerunStageId}"] .rerun-stage`);
      await rerunResponse;
    }
    snapshot.interceptedStarts = interceptedStarts;
    snapshot.interceptedReruns = interceptedReruns;
    snapshot.rerunPayload = rerunPayload;
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
      false,
    );
    const mobile = await inspectPage(
      browser,
      url,
      { width: 390, height: 844 },
      screenshotRoot ? `${screenshotRoot}-mobile.png` : null,
    );
    for (const result of [desktop, mobile]) {
      if (result.snapshot.badge !== "CODEX READY") throw new Error("Codex badge is not ready");
      if (result.snapshot.stageCards !== 24) throw new Error("Expected 24 stage cards");
      const packageCount = result.snapshot.stageCards;
      if (result.snapshot.liveControls !== packageCount) {
        throw new Error(`Expected ${packageCount} live controls`);
      }
      for (const [label, count] of Object.entries({
        modelBadges: result.snapshot.modelBadges,
        rerunControls: result.snapshot.rerunControls,
        rerunButtons: result.snapshot.rerunButtons,
        rerunModels: result.snapshot.rerunModels,
        rerunEfforts: result.snapshot.rerunEfforts,
      })) {
        if (count !== packageCount) throw new Error(`Expected ${packageCount} ${label}`);
      }
      if (result.snapshot.progressPanels !== packageCount * 2) {
        throw new Error(`Expected ${packageCount * 2} progress panels`);
      }
      if (!result.snapshot.liveOverview) throw new Error("Expected persistent live overview");
      if (!result.snapshot.nextAction || !result.snapshot.nextAction.kind) {
        throw new Error("Expected canonical controller nextAction");
      }
      const actionStageId = result.snapshot.nextAction.stageId || "—";
      if (result.snapshot.liveStageId !== actionStageId) {
        throw new Error(
          `Live overview diverges from nextAction: ${result.snapshot.liveStageId} != ${actionStageId}`,
        );
      }
      if (
        result.snapshot.nextAction.stageId
        && !result.snapshot.footerMessage.includes(result.snapshot.nextAction.stageId)
      ) {
        throw new Error("Roadmap footer diverges from canonical nextAction");
      }
      const percent = Number.parseInt(result.snapshot.livePercent, 10);
      if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
        throw new Error(`Invalid live progress: ${result.snapshot.livePercent}`);
      }
      const enabledCoreStarts = result.snapshot.enabledStarts
        .filter(stageId => stageId.startsWith("C"));
      if (enabledCoreStarts.length > 1) {
        throw new Error(`More than one enabled core stage: ${enabledCoreStarts.join(",")}`);
      }
      if (result.snapshot.enabledStarts.some(stageId => !/^[CPR]\d{2}$/.test(stageId))) {
        throw new Error(`Invalid enabled stage ID: ${result.snapshot.enabledStarts.join(",")}`);
      }
      if (result.snapshot.disabledStarts !== packageCount - result.snapshot.enabledStarts.length) {
        throw new Error("Start-button gate count is inconsistent");
      }
      if (result.snapshot.gitStarts !== packageCount) {
        throw new Error(`Expected ${packageCount} Git checkpoint buttons`);
      }
      if (result.snapshot.reviewStarts !== packageCount) {
        throw new Error(`Expected ${packageCount} contract review buttons`);
      }
      if (
        result.snapshot.nextAction.kind === "contract_review"
        && !result.snapshot.enabledReviews.includes(result.snapshot.nextAction.stageId)
      ) {
        throw new Error("Canonical contract review button is not enabled");
      }
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
        if (item.runStatus === "failed" && item.blockedBy.length) {
          return `FAILED · BLOCKED BY ${item.blockedBy.join(", ")}`;
        }
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
      for (const item of result.snapshot.packageSummaries) {
        if (!item.modelLabel) throw new Error(`Missing model label for ${item.id}`);
        if (!item.runtimeExecution) throw new Error(`Missing runtime execution for ${item.id}`);
        if (
          item.model !== (item.runtimeExecution.model || "")
          || item.effort !== (item.runtimeExecution.reasoningEffort || "")
          || item.modelSource !== item.runtimeExecution.source
        ) {
          throw new Error(`Model badge diverges from runtime for ${item.id}`);
        }
        if (item.rerunHidden !== (item.runStatus !== "completed")) {
          throw new Error(`Rerun visibility is wrong for ${item.id}`);
        }
        if (item.rerunDisabled !== !item.runtimeCanRerun) {
          throw new Error(`Rerun gate is wrong for ${item.id}`);
        }
        if (item.rerunModel !== "gpt-5.6-sol" || item.rerunEffort !== "high") {
          throw new Error(`Default rerun settings are wrong for ${item.id}`);
        }
        if (!item.rerunModelOptions || !item.rerunEffortOptions) {
          throw new Error(`Rerun selectors are empty for ${item.id}`);
        }
        if (!item.rerunModelValues.includes("gpt-6-astra")) {
          throw new Error(`Latest model is missing for ${item.id}`);
        }
      }
      if (result.snapshot.executionStats.some(value => !/^\d+$/.test(value))) {
        throw new Error(`Execution stats are not live counts: ${result.snapshot.executionStats.join(",")}`);
      }
      if (result.snapshot.pinnedRegions.length) {
        throw new Error(`Unexpected fixed/sticky regions: ${result.snapshot.pinnedRegions.join(",")}`);
      }
      if (result.snapshot.openDetails !== packageCount) {
        throw new Error(`Expected ${packageCount} expanded C/R/P packages`);
      }
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
    process.stdout.write(`${JSON.stringify({ desktop: desktop.snapshot, mobile: mobile.snapshot })}\n`);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
