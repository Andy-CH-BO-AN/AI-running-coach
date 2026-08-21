const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { JSDOM } = require("jsdom");

const repoRoot = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(repoRoot, "dashboard/index.html"), "utf8");
const adapterSource = fs.readFileSync(path.join(repoRoot, "dashboard/reportAdapter.js"), "utf8");
const appSource = fs.readFileSync(path.join(repoRoot, "dashboard/app.js"), "utf8");

function reportWithSession(session, extra = {}) {
  return {
    weekly_analysis: [{ week_start: "2026-05-11", sessions: [session] }],
    next_week_plan: { week_start: "2026-05-18", days: [] },
    ...extra,
  };
}

function strengthLoadReport(trainingLoad) {
  return reportWithSession({
    date: "2026-05-12",
    source_activity_type: "strength_training",
    distance_km: null,
    duration_min: 45,
    training_load: trainingLoad,
    strength: { total_sets: 4, total_reps: 32, total_volume_kg: null },
  }, {
    meta: { today: "2026-05-12" },
    load_assessment: {
      current_tss_weekly: trainingLoad,
      status: trainingLoad === null ? "unknown" : "undertraining",
      label: trainingLoad === null ? "負荷資料不足" : "本週負荷偏低",
      optimal_tss_range: null,
    },
    twelve_week_summary: [{
      week_start: "2026-05-11",
      week_label: "第1週",
      derived_total_distance_km: 0,
      derived_training_load: trainingLoad,
    }],
  });
}

async function waitForRender(window) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (window.document.getElementById("appStatus").textContent === "") {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error(`dashboard did not finish rendering: ${window.document.getElementById("appStatus").textContent}`);
}

async function renderReport(report) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only",
    url: "http://127.0.0.1:8765/",
  });
  const { window } = dom;
  window.fetch = async (url) => ({
    ok: true,
    status: 200,
    json: async () => String(url) === "/api/reports"
      ? { reports: [{ file: "report.json", is_latest: true }], latest: { file: "report.json" } }
      : report,
  });
  window.eval(adapterSource);
  window.eval(appSource);
  await waitForRender(window);
  return dom;
}

function tableHeaders(document) {
  return [...document.querySelectorAll("#latestActivity .evidence-splits-table th")]
    .map((cell) => cell.textContent);
}

test("report text is rendered as text instead of executable markup", async () => {
  const hostile = '<img data-clean-tests-xss src=x onerror="window.__dashboardInjected=true">';
  const dom = await renderReport(reportWithSession({
    date: "2026-05-12",
    type: "easy",
    source_activity_type: "running",
    coaching_note: hostile,
    observation: hostile,
    segments: [{ segment_type: "lap", distance_km: 1, avg_pace: "05:00", note: hostile }],
  }, {
    evidence_links: [{
      insight_id: "safe-rendering",
      claim: hostile,
      supporting_metrics: [{ label: hostile, value: hostile }],
      confidence: 80,
    }],
  }));

  assert.match(dom.window.document.body.textContent, /data-clean-tests-xss/);
  assert.equal(dom.window.document.querySelector("[data-clean-tests-xss]"), null);
  assert.equal(dom.window.__dashboardInjected, undefined);
  dom.window.close();
});

test("evidence metrics expose values without a source-context column", async () => {
  const dom = await renderReport({
    next_week_plan: { week_start: "2026-05-18", days: [] },
    evidence_links: [{
      insight_id: "load-trend",
      claim: "負荷穩定",
      supporting_metrics: [{ label: "週負荷", value: 120, unit: "TSS", source_path: "weekly_analysis[0].training_load" }],
      confidence: 85,
    }],
  });

  const metricCard = dom.window.document.querySelector(".evidence-metric-card");
  assert.ok(metricCard);
  assert.match(metricCard.textContent, /週負荷/);
  assert.match(metricCard.textContent, /120 TSS/);
  assert.doesNotMatch(dom.window.document.getElementById("evidenceLayer").textContent, /資料脈絡/);
  assert.equal(dom.window.document.querySelector(".evidence-debug-path"), null);
  dom.window.close();
});

test("split mechanics columns follow the fields present in rendered data", async () => {
  const withoutMechanics = await renderReport(reportWithSession({
    date: "2026-05-12",
    type: "easy",
    source_activity_type: "running",
    segments: [{ segment_type: "lap", distance_km: 1, avg_pace: "05:00", avg_hr: 140 }],
  }));
  assert.deepEqual(tableHeaders(withoutMechanics.window.document), ["#", "類型", "距離", "配速", "心率", "備註"]);
  withoutMechanics.window.close();

  const withMechanics = await renderReport(reportWithSession({
    date: "2026-05-12",
    type: "easy",
    source_activity_type: "running",
    segments: [{
      segment_type: "lap",
      distance_km: 1,
      avg_pace: "05:00",
      avg_hr: 140,
      cadence: 180,
      stride_length_m: 1.1,
    }],
  }));
  assert.deepEqual(tableHeaders(withMechanics.window.document), ["#", "類型", "距離", "配速", "心率", "步頻", "步幅", "備註"]);
  withMechanics.window.close();
});

test("latest activity renders splits without requiring an interval layout", async () => {
  const dom = await renderReport(reportWithSession({
    date: "2026-05-12",
    source_activity_type: "running",
    segments: [{ segment_type: "lap", distance_km: 1, avg_pace: "05:00" }],
  }));

  assert.match(dom.window.document.getElementById("latestActivity").textContent, /分段明細/);
  assert.equal(dom.window.document.querySelectorAll("#latestActivity tbody tr").length, 1);
  dom.window.close();
});

test("latest strength activity renders strength facts instead of distance and pace", async () => {
  const dom = await renderReport(reportWithSession({
    date: "2026-05-12",
    source_activity_type: "Strength_Training",
    distance_km: null,
    duration_min: 45,
    training_load: 31,
    avg_hr: 122,
    strength: { total_sets: 16, total_reps: 120, total_volume_kg: 2400 },
  }));

  const latestActivity = dom.window.document.getElementById("latestActivity");
  assert.match(latestActivity.textContent, /時間\s*45\s*分/);
  assert.match(latestActivity.textContent, /訓練負荷\s*31/);
  assert.match(latestActivity.textContent, /總組數\s*16\s*組/);
  assert.match(latestActivity.textContent, /總次數\s*120\s*次/);
  assert.match(latestActivity.textContent, /總容量\s*2400\s*kg/);
  assert.doesNotMatch(latestActivity.textContent, /距離/);
  assert.doesNotMatch(latestActivity.textContent, /配速/);
  dom.window.close();
});

test("unknown strength load stays unavailable across dashboard load surfaces", async () => {
  const dom = await renderReport(strengthLoadReport(null));
  const { document } = dom.window;

  assert.match(document.getElementById("loadAssessment").textContent, /資料不足/);
  assert.match(document.getElementById("weeklyChart").textContent, /資料不足/);
  assert.match(document.getElementById("weeklyChart").textContent, /部分資料不足/);
  assert.match(document.getElementById("weeklyNarratives").textContent, /資料不足/);
  assert.match(document.getElementById("twelveWeekContent").textContent, /資料不足/);
  assert.doesNotMatch(document.getElementById("weeklyChart").textContent, /0\s*TSS/);
  assert.doesNotMatch(document.getElementById("weeklyNarratives").textContent, /0\s*TSS/);
  assert.doesNotMatch(document.getElementById("twelveWeekContent").textContent, /0\s*TSS/);
  assert.equal(document.querySelectorAll(".trend-hit-area.load").length, 0);
  dom.window.close();
});

test("explicit zero strength load remains measured zero across dashboard", async () => {
  const dom = await renderReport(strengthLoadReport(0));
  const { document } = dom.window;

  assert.match(document.getElementById("loadAssessment").textContent, /本週訓練量 \(TSS\)\s*0/);
  assert.match(document.getElementById("weeklyChart").textContent, /0\s*TSS/);
  assert.doesNotMatch(document.getElementById("weeklyChart").textContent, /部分資料不足/);
  assert.match(document.getElementById("weeklyNarratives").textContent, /0\s*TSS/);
  assert.match(document.getElementById("twelveWeekContent").textContent, /0\s*TSS/);
  assert.equal(document.querySelectorAll(".trend-hit-area.load").length, 1);
  dom.window.close();
});

test("cycling splits render speed with km/h units", async () => {
  const dom = await renderReport(reportWithSession({
    date: "2026-05-12",
    type: "ride",
    source_activity_type: "cycling",
    segments: [{ segment_type: "lap", distance_km: 5, speed_kmh: 31.2, avg_hr: 135 }],
  }));

  assert.ok(tableHeaders(dom.window.document).includes("速度"));
  assert.ok(!tableHeaders(dom.window.document).includes("配速"));
  assert.match(dom.window.document.querySelector("#latestActivity tbody").textContent, /31\.2 km\/h/);
  dom.window.close();
});

test("dashboard stylesheet references remain local", () => {
  const dom = new JSDOM(html, { url: "http://127.0.0.1:8765/" });
  const stylesheets = [...dom.window.document.querySelectorAll('link[rel="stylesheet"][href]')];
  assert.ok(stylesheets.length > 0);
  for (const stylesheet of stylesheets) {
    assert.equal(new URL(stylesheet.href).origin, dom.window.location.origin);
  }

  const css = fs.readFileSync(path.join(repoRoot, "dashboard/styles.css"), "utf8");
  assert.doesNotMatch(css, /@import\s+(?:url\()?\s*["']?https?:/i);
  assert.doesNotMatch(css, /url\(\s*["']?https?:/i);
  dom.window.close();
});
