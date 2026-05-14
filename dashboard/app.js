(function runDashboardApp() {
  "use strict";

  var Adapter = window.DashboardAdapter;
  var state = {
    reports: [],
    selectedReport: null,
    model: null
  };

  var elements = {
    appStatus: document.getElementById("appStatus"),
    reportSelect: document.getElementById("reportSelect"),
    reloadButton: document.getElementById("reloadButton"),
    statusGrid: document.getElementById("statusGrid"),
    coachSummary: document.getElementById("coachSummary"),
    loadAssessment: document.getElementById("loadAssessment"),
    weeklyChart: document.getElementById("weeklyChart"),
    weeklyNarratives: document.getElementById("weeklyNarratives"),
    hrZones: document.getElementById("hrZones"),
    raceReadiness: document.getElementById("raceReadiness"),
    planTheme: document.getElementById("planTheme"),
    weeklyCalendar: document.getElementById("weeklyCalendar"),
    physioMetrics: document.getElementById("physioMetrics"),
    runningMechanics: document.getElementById("runningMechanics"),
    evidenceLayer: document.getElementById("evidenceLayer")
  };

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function el(tagName, className, text) {
    var node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function svgEl(tagName, attrs) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tagName);
    Object.keys(attrs || {}).forEach(function setAttr(key) {
      node.setAttribute(key, attrs[key]);
    });
    return node;
  }

  function append(parent) {
    Array.prototype.slice.call(arguments, 1).forEach(function appendNode(child) {
      if (child !== null && child !== undefined) {
        parent.appendChild(child);
      }
    });
    return parent;
  }

  function setStatus(message, isError) {
    elements.appStatus.textContent = message || "";
    elements.appStatus.className = message
      ? "app-status is-visible" + (isError ? " is-error" : "")
      : "app-status";
  }

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function parseResponse(response) {
      if (!response.ok) {
        throw new Error("HTTP " + String(response.status));
      }

      return response.json();
    });
  }

  function formatValue(value, suffix) {
    if (value === null || value === undefined || value === "") {
      return "資料不足";
    }

    return String(value) + (suffix || "");
  }

  function metricLine(label, value) {
    var node = el("span", null);
    append(node, el("strong", null, label + " "), document.createTextNode(value));
    return node;
  }

  function sourceCell(label, rawPath) {
    var node = el("td", "source-path", label || "資料來源不足");
    if (rawPath) {
      node.title = rawPath;
    }
    return node;
  }

  function renderStatusCards(model) {
    clear(elements.statusGrid);
    model.status_cards.forEach(function renderCard(card) {
      var node = el("article", "status-card " + card.state);
      var score = el("div", "status-score");
      append(score, el("strong", null, card.score === null ? "--" : card.score), el("span", null, "/100"));
      var trend = el("span", "trend-pill " + card.trend.className);
      append(trend, document.createTextNode((card.trend.symbol ? card.trend.symbol + " " : "") + card.trend.label));
      append(
        node,
        el("p", "status-title", card.title),
        score,
        el("p", "status-label", card.label),
        trend
      );
      elements.statusGrid.appendChild(node);
    });
  }

  function makeEvidenceButton(evidenceId) {
    if (!evidenceId) {
      return null;
    }

    var button = el("button", "evidence-link", "依據");
    button.type = "button";
    button.addEventListener("click", function scrollToEvidence() {
      var target = document.getElementById("evidence-" + evidenceId);
      if (target) {
        target.open = true;
        target.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
    return button;
  }

  function renderSummaryList(title, items) {
    var block = el("div");
    append(block, el("p", "metric-title", title));
    var list = el("ul", "summary-list");
    items.forEach(function addItem(item) {
      var row = el("li");
      append(row, el("span", null, item.text || "資料不足"));
      append(row, makeEvidenceButton(item.evidence_id));
      list.appendChild(row);
    });
    if (items.length === 0) {
      list.appendChild(el("li", null, "資料不足"));
    }
    append(block, list);
    return block;
  }

  function renderCoachSummary(model) {
    clear(elements.coachSummary);
    var summary = model.coaching_summary;
    var columns = el("div", "summary-columns");
    append(
      columns,
      renderSummaryList("三個洞察", summary.top_3_insights),
      renderSummaryList("三個行動", summary.top_3_actions)
    );
    append(elements.coachSummary, el("p", "summary-headline", summary.headline), columns);
  }

  function renderLoadAssessment(model) {
    clear(elements.loadAssessment);
    var load = model.load_assessment;
    var meter = el("div", "load-meter");
    var value = el("div", "load-value");
    append(value, el("strong", null, load.current_tss_weekly === null ? "--" : load.current_tss_weekly), el("span", null, "weekly TSS"));

    var max = load.optimal_tss_range && load.optimal_tss_range.max ? Number(load.optimal_tss_range.max) : Math.max(100, Number(load.current_tss_weekly) || 100);
    var width = load.current_tss_weekly === null ? 0 : Math.min(100, Math.max(0, (Number(load.current_tss_weekly) / max) * 100));
    var bar = el("div", "range-bar");
    var fill = el("div", "range-fill");
    fill.style.width = String(width) + "%";
    bar.appendChild(fill);

    append(
      meter,
      value,
      el("p", "status-label", load.label),
      bar,
      el("p", "subtle", load.optimal_tss_range ? "建議範圍 " + load.optimal_tss_range.min + "-" + load.optimal_tss_range.max : "建議範圍資料不足"),
      el("p", null, load.recommendation)
    );
    elements.loadAssessment.appendChild(meter);
  }

  function renderWeeklyChart(model) {
    clear(elements.weeklyChart);
    var weeks = model.weekly_analysis.chronological;
    if (!weeks.length) {
      elements.weeklyChart.appendChild(el("div", "chart-empty", "週資料不足，尚無法繪製趨勢。"));
      return;
    }

    var width = 760;
    var height = 320;
    var padding = { top: 26, right: 34, bottom: 48, left: 48 };
    var plotWidth = width - padding.left - padding.right;
    var plotHeight = height - padding.top - padding.bottom;
    var maxDistance = Math.max.apply(null, weeks.map(function readDistance(week) {
      return week.metrics.derived_total_distance_km;
    }).concat([1]));
    var maxLoad = Math.max.apply(null, weeks.map(function readLoad(week) {
      return week.metrics.derived_training_load;
    }).concat([1]));
    var step = weeks.length > 1 ? plotWidth / (weeks.length - 1) : 0;

    function x(index) {
      if (weeks.length === 1) {
        return padding.left + plotWidth / 2;
      }

      return padding.left + step * index;
    }

    function yDistance(value) {
      return padding.top + plotHeight - (value / maxDistance) * plotHeight;
    }

    function yLoad(value) {
      return padding.top + plotHeight - (value / maxLoad) * plotHeight;
    }

    var svg = svgEl("svg", {
      class: "chart-svg",
      viewBox: "0 0 " + String(width) + " " + String(height),
      role: "img",
      "aria-label": "週跑量與訓練負荷趨勢"
    });

    [0, 0.25, 0.5, 0.75, 1].forEach(function addGrid(ratio) {
      var y = padding.top + plotHeight * ratio;
      svg.appendChild(svgEl("line", {
        class: "grid-line",
        x1: padding.left,
        y1: y,
        x2: width - padding.right,
        y2: y
      }));
    });

    weeks.forEach(function addBar(week, index) {
      var barWidth = Math.max(26, plotWidth / Math.max(weeks.length, 4) * 0.42);
      var barHeight = padding.top + plotHeight - yLoad(week.metrics.derived_training_load);
      svg.appendChild(svgEl("rect", {
        class: "load-bar",
        x: x(index) - barWidth / 2,
        y: yLoad(week.metrics.derived_training_load),
        width: barWidth,
        height: Math.max(2, barHeight),
        rx: 4
      }));
    });

    var path = weeks.map(function point(week, index) {
      return (index === 0 ? "M" : "L") + x(index) + " " + yDistance(week.metrics.derived_total_distance_km);
    }).join(" ");
    svg.appendChild(svgEl("path", { class: "distance-line", d: path }));

    weeks.forEach(function addDot(week, index) {
      svg.appendChild(svgEl("circle", {
        class: "distance-dot",
        cx: x(index),
        cy: yDistance(week.metrics.derived_total_distance_km),
        r: 5
      }));

      var label = svgEl("text", {
        class: "chart-label",
        x: x(index),
        y: height - 18,
        "text-anchor": "middle"
      });
      label.textContent = week.week_start_label;
      svg.appendChild(label);

      var value = svgEl("text", {
        class: "chart-label",
        x: x(index),
        y: yDistance(week.metrics.derived_total_distance_km) - 10,
        "text-anchor": "middle"
      });
      value.textContent = week.metrics.derived_total_distance_km + "km";
      svg.appendChild(value);
    });

    var leftLabel = svgEl("text", { class: "axis-label", x: 2, y: 18 });
    leftLabel.textContent = "km";
    var rightLabel = svgEl("text", { class: "axis-label", x: width - 42, y: 18 });
    rightLabel.textContent = "load";
    append(svg, leftLabel, rightLabel);
    elements.weeklyChart.appendChild(svg);
  }

  function renderWeeklyNarratives(model) {
    clear(elements.weeklyNarratives);
    model.weekly_analysis.weeks.forEach(function addWeek(week) {
      var node = el("article", "week-item");
      var top = el("div", "week-topline");
      var qualityClass = week.metrics.data_quality === "部分資料不足" ? "quality-pill partial" : "quality-pill";
      append(top, el("h3", "week-title", week.week_label), el("span", qualityClass, week.metrics.data_quality));

      var metrics = el("div", "week-metrics");
      append(
        metrics,
        metricLine("跑量", week.metrics.derived_total_distance_km + " km"),
        metricLine("時間", week.metrics.derived_total_duration_min + " min"),
        metricLine("負荷", String(week.metrics.derived_training_load))
      );

      append(
        node,
        top,
        metrics,
        el("p", null, week.key_observation),
        el("p", "subtle", week.weekly_assessment),
        el("p", null, week.weekly_recommendation)
      );

      if (week.risk_flags.length) {
        var risks = el("div", "risk-list");
        week.risk_flags.forEach(function addRisk(risk) {
          var pill = el("span", "tag", risk.label || risk.code || "風險提醒");
          if (risk.code) {
            pill.title = risk.code;
          }
          risks.appendChild(pill);
        });
        node.appendChild(risks);
      }

      elements.weeklyNarratives.appendChild(node);
    });
  }

  function renderHrZones(model) {
    clear(elements.hrZones);
    var data = model.hr_zones;
    if (!data.has_data) {
      elements.hrZones.appendChild(el("div", "empty-state", "心率區間資料不足。"));
      return;
    }

    var stack = el("div", "zone-stack");
    data.zones.forEach(function addSegment(zone) {
      var segment = el("div", "zone-segment");
      segment.style.width = String(Math.max(0, zone.percentage)) + "%";
      segment.style.background = zone.color;
      segment.textContent = zone.percentage >= 8 ? "Z" + zone.zone : "";
      stack.appendChild(segment);
    });

    var list = el("div", "zone-list");
    data.zones.forEach(function addZone(zone) {
      var item = el("div", "zone-item");
      var name = el("div", "zone-name");
      var dot = el("span", "zone-dot");
      dot.style.background = zone.color;
      append(name, dot, document.createTextNode("Z" + zone.zone + " " + zone.name));
      append(item, name, el("div", "zone-value", zone.percentage + "% · " + zone.minutes + " min"));
      list.appendChild(item);
    });

    var copy = el("div", "assessment-copy");
    append(copy, el("p", null, data.assessment), el("p", "subtle", data.recommendation));
    append(elements.hrZones, stack, list, copy);
  }

  function renderRaceReadiness(model) {
    clear(elements.raceReadiness);
    var readiness = model.race_readiness;
    var row = el("div", "race-score-row");
    var ring = el("div", "score-ring");
    ring.style.setProperty("--score", readiness.confidence_score || 0);
    ring.appendChild(el("div", "score-ring-inner", readiness.confidence_score === null ? "--" : readiness.confidence_score));
    var copy = el("div");
    append(
      copy,
      el("p", "status-label", readiness.confidence_label),
      el("p", "subtle", readiness.race_name + " · " + readiness.race_date_label)
    );
    append(row, ring, copy);

    var list = el("div", "capability-list");
    if (readiness.missing_capabilities.length === 0) {
      list.appendChild(el("div", "empty-state", "目前沒有能力缺口資料。"));
    }
    readiness.missing_capabilities.forEach(function addCapability(item) {
      var node = el("div", "capability-item");
      var title = el("p", "capability-title");
      append(title, el("span", null, item.capability), el("span", "priority-pill " + item.priority, item.priority_label));
      append(node, title, el("p", "subtle", item.training_suggestion));
      list.appendChild(node);
    });

    append(elements.raceReadiness, row, list);
  }

  function renderCalendar(model) {
    clear(elements.weeklyCalendar);
    var plan = model.next_week_plan;
    elements.planTheme.textContent = plan.theme + " · " + plan.total_distance_km + " km";

    plan.days.forEach(function addDay(day) {
      var node = el("article", "calendar-day");
      var date = el("div", "calendar-date");
      append(date, el("span", null, day.day_label), el("span", null, day.date_label));
      var meta = el("div", "calendar-meta");
      append(
        meta,
        el("span", "intensity-pill " + day.intensity_class, day.intensity_label),
        day.key_workout ? el("span", "intensity-pill key-workout", "Key") : null
      );

      append(
        node,
        date,
        el("p", "calendar-title", day.title),
        meta,
        el("p", "subtle", day.session_type_label + " · " + day.duration_min + " min · " + day.distance_km + " km")
      );

      if (day.description) {
        node.appendChild(el("p", null, day.description));
      }

      if (day.weather_consideration && day.weather_consideration !== "無") {
        node.appendChild(el("p", "subtle", day.weather_consideration));
      }

      elements.weeklyCalendar.appendChild(node);
    });
  }

  function renderPhysioMetrics(model) {
    clear(elements.physioMetrics);
    var physio = model.physio_metrics;
    var grid = el("div", "physio-grid");
    var ltPace = physio.lactate_threshold.pace.value + physio.lactate_threshold.pace.unit;
    var ltHr = formatValue(physio.lactate_threshold.heart_rate.value, " " + physio.lactate_threshold.heart_rate.unit);
    var tiles = [
      ["VO2max", formatValue(physio.vo2max.value, " " + physio.vo2max.unit), physio.vo2max.assessment],
      ["乳酸閾值心率", ltHr, physio.lactate_threshold.assessment],
      ["乳酸閾值配速", ltPace, physio.lactate_threshold.pace.assessment],
      ["靜息 / 最大心率", formatValue(physio.resting_heart_rate.value, "") + " / " + formatValue(physio.max_heart_rate.value, "") + " bpm", ""]
    ];

    tiles.forEach(function addTile(item) {
      var node = el("div", "metric-tile");
      append(node, el("p", "metric-title", item[0]), el("p", "metric-value", item[1]), item[2] ? el("p", "metric-copy", item[2]) : null);
      grid.appendChild(node);
    });

    var tableWrap = el("div", "pace-table-wrap");
    var table = el("table", "pace-table");
    var thead = el("thead");
    var headRow = el("tr");
    ["Zone", "名稱", "配速", "心率", "備註"].forEach(function addHead(label) {
      headRow.appendChild(el("th", null, label));
    });
    thead.appendChild(headRow);
    var tbody = el("tbody");
    if (!physio.has_pace_zones) {
      var emptyRow = el("tr");
      var emptyCell = el("td", null, "配速區間資料不足。");
      emptyCell.colSpan = 5;
      emptyRow.appendChild(emptyCell);
      tbody.appendChild(emptyRow);
    }
    physio.pace_zones.forEach(function addZone(zone) {
      var row = el("tr");
      append(
        row,
        el("td", null, "Z" + zone.zone),
        el("td", null, zone.name),
        el("td", null, zone.pace_range || zone.pace_min + " - " + zone.pace_max),
        el("td", null, formatValue(zone.hr_min, "") + " - " + formatValue(zone.hr_max, "")),
        el("td", null, zone.note || "")
      );
      tbody.appendChild(row);
    });
    append(table, thead, tbody);
    tableWrap.appendChild(table);
    append(elements.physioMetrics, grid, tableWrap);
  }

  function renderRunningMechanics(model) {
    clear(elements.runningMechanics);
    var mechanics = model.running_mechanics;
    var grid = el("div", "mechanic-grid");
    mechanics.metrics.forEach(function addMetric(metric) {
      var node = el("div", "mechanic-item");
      append(
        node,
        el("p", "metric-title", metric.title),
        el("p", "metric-value", metric.display_value + (metric.has_data ? " " + metric.unit : "")),
        metric.assessment ? el("p", "metric-copy", metric.assessment) : null
      );
      grid.appendChild(node);
    });

    var economy = el("div", "metric-tile");
    append(economy, el("p", "metric-title", "跑步經濟性"), el("p", "metric-value", mechanics.running_economy_label), el("p", "metric-copy", "score / 100"));

    var tips = el("ul", "tips-list");
    if (!mechanics.improvement_tips.length) {
      tips.appendChild(el("li", null, "尚無跑姿建議。"));
    }
    mechanics.improvement_tips.forEach(function addTip(tip) {
      tips.appendChild(el("li", null, tip));
    });
    append(elements.runningMechanics, grid, economy, tips);
  }

  function renderEvidenceLayer(model) {
    clear(elements.evidenceLayer);
    var evidence = model.evidence;
    if (!evidence.hasEvidence) {
      elements.evidenceLayer.appendChild(el("div", "empty-state", evidence.fallbackMessage));
      return;
    }

    var list = el("div", "evidence-list");
    evidence.items.forEach(function addEvidence(item) {
      var details = el("details", "evidence-card");
      details.id = "evidence-" + item.id;
      var summary = el("summary");
      var text = el("span", "evidence-summary-text", item.claim);
      var meta = el("span", "evidence-meta");
      append(
        meta,
        item.high_risk ? el("span", "tag", "風險優先") : null,
        el("span", "source-pill confidence-pill", "可信度 " + item.confidence),
        el("span", "source-pill", item.visualization_label || item.visualization_hint)
      );
      append(summary, text, meta);

      var body = el("div", "evidence-body");
      append(body, renderEvidenceMetrics(item), renderEvidenceSessions(item));
      if (item.source_sections.length) {
        var sources = el("div", "risk-list");
        item.source_section_labels.forEach(function addSource(sectionLabel, index) {
          var pill = el("span", "source-pill", sectionLabel);
          if (item.source_sections[index]) {
            pill.title = item.source_sections[index];
          }
          sources.appendChild(pill);
        });
        body.appendChild(sources);
      }

      append(details, summary, body);
      list.appendChild(details);
    });
    elements.evidenceLayer.appendChild(list);
  }

  function renderEvidenceMetrics(item) {
    var block = el("div");
    append(block, el("p", "metric-title", "關鍵數值"));
    if (!item.supporting_metrics.length) {
      block.appendChild(el("p", "subtle", "沒有數值依據。"));
      return block;
    }

    var table = el("table", "evidence-table");
    var thead = el("thead");
    var head = el("tr");
    ["指標", "值", "解讀", "資料來源"].forEach(function addHead(label) {
      head.appendChild(el("th", null, label));
    });
    thead.appendChild(head);
    var tbody = el("tbody");
    item.supporting_metrics.forEach(function addMetric(metric) {
      var row = el("tr");
      append(
        row,
        el("td", null, metric.label || "指標"),
        el("td", null, formatValue(metric.value, metric.unit ? " " + metric.unit : "")),
        el("td", null, metric.interpretation || ""),
        sourceCell(metric.source_label, metric.source_path)
      );
      tbody.appendChild(row);
    });
    append(table, thead, tbody);
    block.appendChild(table);
    return block;
  }

  function renderEvidenceSessions(item) {
    var block = el("div");
    append(block, el("p", "metric-title", "相關活動"));
    if (!item.supporting_sessions.length) {
      block.appendChild(el("p", "subtle", "沒有活動依據。"));
      return block;
    }

    var table = el("table", "evidence-table");
    var thead = el("thead");
    var head = el("tr");
    ["日期", "類型", "距離/時間", "HR/配速", "原因", "資料來源"].forEach(function addHead(label) {
      head.appendChild(el("th", null, label));
    });
    thead.appendChild(head);
    var tbody = el("tbody");
    item.supporting_sessions.forEach(function addSession(session) {
      var row = el("tr");
      append(
        row,
        el("td", null, session.date || "日期不足"),
        el("td", null, session.type || "類型不足"),
        el("td", null, formatValue(session.distance_km, " km") + " / " + formatValue(session.duration_min, " min")),
        el("td", null, formatValue(session.avg_hr, " bpm") + " / " + formatValue(session.avg_pace, "")),
        el("td", null, session.reason || ""),
        sourceCell(session.source_label, session.source_path)
      );
      tbody.appendChild(row);
      if (session.segments && session.segments.length) {
        tbody.appendChild(renderSessionSegmentsRow(session));
      }
    });
    append(table, thead, tbody);
    block.appendChild(table);
    return block;
  }

  function renderSessionSegmentsRow(session) {
    var row = el("tr", "segment-row");
    var cell = el("td", "segment-cell");
    cell.colSpan = 6;
    var title = el("p", "segment-title", "分段明細");
    var table = el("table", "segment-table");
    var thead = el("thead");
    var head = el("tr");
    ["段落", "距離", "配速", "HR", "步頻", "備註"].forEach(function addHead(label) {
      head.appendChild(el("th", null, label));
    });
    thead.appendChild(head);
    var tbody = el("tbody");
    session.segments.forEach(function addSegment(segment) {
      var segmentRow = el("tr");
      append(
        segmentRow,
        el("td", null, segment.segment_type_label + " " + segment.index),
        el("td", null, formatValue(segment.distance_km, " km")),
        el("td", null, formatValue(segment.avg_pace, "")),
        el("td", null, formatValue(segment.avg_hr, " bpm")),
        el("td", null, formatValue(segment.cadence, " spm")),
        el("td", null, segment.note || "")
      );
      tbody.appendChild(segmentRow);
    });
    append(table, thead, tbody);
    append(cell, title, table);
    row.appendChild(cell);
    return row;
  }

  function render(model) {
    renderStatusCards(model);
    renderCoachSummary(model);
    renderLoadAssessment(model);
    renderWeeklyChart(model);
    renderWeeklyNarratives(model);
    renderHrZones(model);
    renderRaceReadiness(model);
    renderCalendar(model);
    renderPhysioMetrics(model);
    renderRunningMechanics(model);
    renderEvidenceLayer(model);
  }

  function populateReportSelect(reports, latest) {
    clear(elements.reportSelect);
    reports.forEach(function addOption(report) {
      var option = document.createElement("option");
      option.value = report.file;
      option.textContent = report.file + (report.is_latest ? " · latest" : "");
      elements.reportSelect.appendChild(option);
    });

    var selected = state.selectedReport || (latest && latest.file) || (reports[0] && reports[0].file);
    if (selected) {
      elements.reportSelect.value = selected;
      state.selectedReport = selected;
    }
  }

  function loadReport(fileName) {
    if (!fileName) {
      setStatus("找不到 output/ai_report_YYYYMMDD.json，請先產生 JSON 報告。", true);
      return Promise.resolve();
    }

    setStatus("正在載入 " + fileName + "...", false);
    return fetchJson("/api/reports/" + encodeURIComponent(fileName)).then(function handleReport(report) {
      state.selectedReport = fileName;
      state.model = Adapter.buildDashboardModel(report);
      render(state.model);
      setStatus("", false);
    }).catch(function handleError(error) {
      setStatus("載入報告失敗：" + error.message, true);
    });
  }

  function loadReportList() {
    setStatus("正在掃描 output/ 報告...", false);
    return fetchJson("/api/reports").then(function handleList(payload) {
      state.reports = payload.reports || [];
      populateReportSelect(state.reports, payload.latest);
      return loadReport(state.selectedReport);
    }).catch(function handleError(error) {
      setStatus("載入報告清單失敗：" + error.message, true);
    });
  }

  elements.reportSelect.addEventListener("change", function onReportChange(event) {
    loadReport(event.target.value);
  });
  elements.reloadButton.addEventListener("click", function onReload() {
    loadReportList();
  });

  loadReportList();
})();
