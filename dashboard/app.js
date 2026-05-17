(function app() {
  "use strict";

  var Adapter = window.DashboardAdapter;
  var state = {
    reports: [],
    selectedReport: null,
    model: null
  };

  var elements = {
    reportSelect: document.getElementById("reportSelect"),
    reloadButton: document.getElementById("reloadButton"),
    appStatus: document.getElementById("appStatus"),
    primaryAction: document.getElementById("primaryAction"),
    statusGrid: document.getElementById("statusGrid"),
    coachSummary: document.getElementById("coachSummary"),
    loadAssessment: document.getElementById("loadAssessment"),
    raceReadiness: document.getElementById("raceReadiness"),
    latestActivity: document.getElementById("latestActivity"),
    weeklyChart: document.getElementById("weeklyChart"),
    weeklyNarratives: document.getElementById("weeklyNarratives"),
    twelveWeekContent: document.getElementById("twelveWeekContent"),
    weeklyCalendar: document.getElementById("weeklyCalendar"),
    planSummary: document.getElementById("planSummary"),
    planAdjustment: document.getElementById("planAdjustment"),
    hrZones: document.getElementById("hrZones"),
    intensityZones: document.getElementById("intensityZones"),
    physioMetrics: document.getElementById("physioMetrics"),
    runningMechanics: document.getElementById("runningMechanics"),
    evidenceLayer: document.getElementById("evidenceLayer")
  };

  function isDebugMode() {
    return window.location.search.indexOf("debug=1") !== -1;
  }

  function confidencePillClass(confidence) {
    if (confidence >= 80) {
      return "green";
    }
    if (confidence >= 60) {
      return "amber";
    }
    return "red";
  }

  function setStatus(text, isError) {
    elements.appStatus.textContent = text;
    elements.appStatus.className = text
      ? "app-status is-visible" + (isError ? " is-error" : "")
      : "app-status";
  }

  function clear(element) {
    if (!element) return;
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function validate(response) {
      if (!response.ok) {
        throw new Error("HTTP error " + response.status);
      }
      return response.json();
    });
  }

  function textElement(tagName, className, text) {
    var node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    node.textContent = text;
    return node;
  }

  function appendLabeledCopy(container, className, labelText, bodyText) {
    var paragraph = document.createElement("p");
    paragraph.className = className;
    paragraph.appendChild(textElement("strong", "", labelText + "："));
    paragraph.appendChild(document.createTextNode(bodyText));
    container.appendChild(paragraph);
  }

  function appendTableCells(row, values, boldIndex) {
    values.forEach(function(value, index) {
      var cell = document.createElement("td");
      if (index === boldIndex) {
        cell.appendChild(textElement("b", "", value));
      } else {
        cell.textContent = value;
      }
      row.appendChild(cell);
    });
  }

  function renderPrimaryAction(model) {
    var primary = model.primary_action;
    clear(elements.primaryAction);

    var container = document.createElement("div");
    container.className = "primary-action-bar state-" + primary.statusClass;

    var textBlock = document.createElement("div");
    var title = document.createElement("h3");
    title.className = "primary-action-title";
    title.textContent = "🏃 " + primary.todayAction;
    var sub = document.createElement("p");
    sub.className = "primary-action-sub";
    sub.textContent = primary.rationale;
    textBlock.appendChild(title);
    textBlock.appendChild(sub);

    var badge = document.createElement("div");
    badge.className = "primary-action-badge " + primary.statusClass;
    badge.textContent = primary.statusBadge;

    container.appendChild(textBlock);
    container.appendChild(badge);
    elements.primaryAction.appendChild(container);
  }

  function renderStatusCards(model) {
    clear(elements.statusGrid);
    model.status_cards.forEach(function(card) {
      var node = document.createElement("article");
      node.className = "status-card " + card.state;

      var title = document.createElement("p");
      title.className = "status-title";
      title.textContent = card.title;

      var score = document.createElement("div");
      score.className = "status-score";
      var strong = document.createElement("strong");
      strong.textContent = card.score === null ? "--" : card.score;
      var unit = document.createElement("span");
      unit.textContent = "/100";
      score.appendChild(strong);
      score.appendChild(unit);

      var label = document.createElement("p");
      label.className = "status-label";
      label.textContent = card.label;

      var trend = document.createElement("span");
      trend.className = "trend-pill " + card.trend.className;
      trend.textContent = (card.trend.symbol ? card.trend.symbol + " " : "") + card.trend.label;

      node.appendChild(title);
      node.appendChild(score);
      node.appendChild(label);
      node.appendChild(trend);
      elements.statusGrid.appendChild(node);
    });
  }

  function renderCoachSummary(model) {
    var summary = model.coaching_summary;
    clear(elements.coachSummary);

    var headline = document.createElement("p");
    headline.className = "headline-text";
    headline.textContent = summary.headline;
    elements.coachSummary.appendChild(headline);

    var grid = document.createElement("div");
    grid.className = "summary-columns";

    var insightsCol = document.createElement("div");
    insightsCol.appendChild(textElement("h3", "", "教練觀察"));
    var insightsList = document.createElement("ul");
    summary.top_3_insights.forEach(function(item) {
      var li = document.createElement("li");
      li.textContent = item.text;
      insightsList.appendChild(li);
    });
    insightsCol.appendChild(insightsList);

    var actionsCol = document.createElement("div");
    actionsCol.appendChild(textElement("h3", "", "下一步建議"));
    var actionsList = document.createElement("ul");
    summary.top_3_actions.forEach(function(item) {
      var li = document.createElement("li");
      li.textContent = item.text;
      actionsList.appendChild(li);
    });
    actionsCol.appendChild(actionsList);

    grid.appendChild(insightsCol);
    grid.appendChild(actionsCol);
    elements.coachSummary.appendChild(grid);
  }

  function renderLoadAssessment(model) {
    var load = model.load_assessment;
    clear(elements.loadAssessment);

    var caption = document.createElement("p");
    caption.className = "subtle load-caption";
    caption.textContent = "本週訓練量 (TSS)";

    var score = document.createElement("div");
    score.className = "stat-value large";
    score.textContent = load.current_tss_weekly || "0";

    var label = document.createElement("div");
    label.className = "pill " + load.status;
    label.textContent = load.label;

    var range = document.createElement("p");
    range.className = "subtle";
    if (load.optimal_tss_range) {
      range.textContent = "建議範圍: " + load.optimal_tss_range.min + " - " + load.optimal_tss_range.max;
    }

    elements.loadAssessment.appendChild(caption);
    elements.loadAssessment.appendChild(score);
    elements.loadAssessment.appendChild(label);
    elements.loadAssessment.appendChild(range);
  }

  function renderRaceReadiness(model) {
    var race = model.race_readiness;
    clear(elements.raceReadiness);

    var score = document.createElement("div");
    score.className = "stat-value large";
    score.textContent = race.confidence_score || "0";

    var name = document.createElement("p");
    name.className = "subtle";
    name.textContent = race.race_name + " (" + race.race_date_label + ")";

    elements.raceReadiness.appendChild(score);
    if (race.confidence_label) {
      var label = document.createElement("div");
      label.className = "pill good race-readiness-label";
      label.textContent = race.confidence_label;
      elements.raceReadiness.appendChild(label);
    }
    elements.raceReadiness.appendChild(name);

    if (race.missing_capabilities.length > 0) {
      var list = document.createElement("div");
      list.className = "capability-list compact";
      race.missing_capabilities.forEach(function(item) {
        var capability = document.createElement("div");
        capability.className = "capability-item";
        var title = document.createElement("p");
        title.className = "capability-title";
        title.textContent = item.capability;
        var priority = document.createElement("span");
        priority.className = "priority-pill " + item.priority;
        priority.textContent = item.priority_label;
        title.appendChild(priority);
        var suggestion = document.createElement("p");
        suggestion.className = "subtle";
        suggestion.textContent = item.training_suggestion;
        capability.appendChild(title);
        capability.appendChild(suggestion);
        list.appendChild(capability);
      });
      elements.raceReadiness.appendChild(list);
    }
  }

  function renderActivityStat(label, value, unit) {
    var div = document.createElement("div");
    div.className = "activity-stat";
    div.appendChild(textElement("span", "stat-label", label));
    var valueWrap = document.createElement("span");
    valueWrap.className = "stat-value";
    valueWrap.appendChild(document.createTextNode(String(value)));
    valueWrap.appendChild(document.createTextNode(" "));
    valueWrap.appendChild(textElement("span", "stat-unit", unit));
    div.appendChild(valueWrap);
    return div;
  }

  function renderRepSparkline(reps) {
    var wrap = document.createElement("div");
    wrap.className = "rep-sparkline-wrap";
    var width = 520;
    var height = 90;
    var pad = 18;
    var ns = "http://www.w3.org/2000/svg";
    var paces = reps.map(function pickPace(rep) {
      var raw = rep.avg_pace || "";
      var parts = String(raw).replace(/\/km/gi, "").trim().split(":");
      if (parts.length !== 2) {
        return null;
      }
      return Number(parts[0]) * 60 + Number(parts[1]);
    }).filter(function keep(value) { return Number.isFinite(value); });

    if (paces.length < 2) {
      wrap.appendChild(textElement("p", "subtle", "分段資料不足，無法繪製趨勢圖。"));
      return wrap;
    }

    var minPace = Math.min.apply(null, paces);
    var maxPace = Math.max.apply(null, paces);
    var range = Math.max(maxPace - minPace, 20);
    var plotW = width - pad * 2;
    var plotH = height - pad * 2;
    var step = plotW / (paces.length - 1);
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("class", "rep-sparkline-svg");
    var points = paces.map(function mapPoint(value, index) {
      var x = pad + index * step;
      var y = pad + ((value - minPace) / range) * plotH;
      return x + "," + y;
    }).join(" ");
    var polyline = document.createElementNS(ns, "polyline");
    polyline.setAttribute("points", points);
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke", "var(--blue)");
    polyline.setAttribute("stroke-width", "3");
    svg.appendChild(polyline);
    paces.forEach(function drawDot(value, index) {
      var circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", pad + index * step);
      circle.setAttribute("cy", pad + ((value - minPace) / range) * plotH);
      circle.setAttribute("r", "4");
      circle.setAttribute("fill", "var(--panel)");
      circle.setAttribute("stroke", "var(--blue)");
      circle.setAttribute("stroke-width", "3");
      svg.appendChild(circle);
    });
    wrap.appendChild(svg);
    return wrap;
  }

  function renderLatestActivity(model) {
    clear(elements.latestActivity);
    var latest = model.latest_activity;

    if (!latest || !latest.has_data) {
      elements.latestActivity.appendChild(textElement("p", "subtle", "尚無近期活動紀錄。"));
      return;
    }

    var flag = document.createElement("div");
    flag.className = "activity-type-flag";
    flag.textContent = latest.date_label + " · " + latest.type_label;
    elements.latestActivity.appendChild(flag);

    var conclusion = document.createElement("div");
    conclusion.className = "activity-conclusion" + (latest.has_ai_conclusion ? "" : " missing-ai");
    var conclusionText = document.createElement("p");
    conclusionText.textContent = latest.has_ai_conclusion
      ? "本次結論：" + latest.conclusion
      : "AI 教練結論尚未產生；以下先顯示這次訓練的客觀數據。";
    conclusion.appendChild(conclusionText);
    elements.latestActivity.appendChild(conclusion);

    var stats = document.createElement("div");
    stats.className = "activity-stat-grid";
    stats.appendChild(renderActivityStat("距離", latest.distance_km || "0", "km"));
    stats.appendChild(renderActivityStat("配速", latest.avg_pace || "--:--", "/km"));
    stats.appendChild(renderActivityStat("心率", latest.avg_hr || "--", "bpm"));
    stats.appendChild(renderActivityStat("氣溫", latest.temperature_c !== null ? latest.temperature_c : "--", "°C"));
    elements.latestActivity.appendChild(stats);

    if (latest.layout === "interval" && latest.work_reps.length > 0) {
      var trend = document.createElement("details");
      trend.className = "rep-trend-details";
      trend.open = true;
      trend.appendChild(textElement("summary", "", "重點分段趨勢"));
      if (latest.rep_trend_label) {
        var trendText = document.createElement("p");
        trendText.className = "rep-sparkline-note";
        trendText.textContent = latest.rep_trend_label;
        trend.appendChild(trendText);
      }
      trend.appendChild(renderRepSparkline(latest.work_reps));
      elements.latestActivity.appendChild(trend);
    }

    var notes = latest.coaching_notes || {};
    var noteBlocks = [
      { label: "教練觀察", text: notes.observation },
      { label: "訓練解讀", text: notes.interpretation },
      { label: "下一步建議", text: notes.recommendation }
    ].filter(function keep(block) { return block.text; });

    if (noteBlocks.length > 0) {
      var stack = document.createElement("div");
      stack.className = "coach-notes-stack";
      noteBlocks.forEach(function addNote(block) {
        var card = document.createElement("div");
        card.className = "coach-note-card";
        card.appendChild(textElement("span", "coach-note-label", block.label));
        card.appendChild(textElement("p", "", block.text));
        stack.appendChild(card);
      });
      elements.latestActivity.appendChild(stack);
    }
  }

  function renderWeeklyChart(model) {
    var weeks = model.weekly_analysis.chronological;
    clear(elements.weeklyChart);

    if (weeks.length === 0) {
      elements.weeklyChart.appendChild(textElement("div", "chart-empty", "尚無訓練資料"));
      return;
    }

    var maxDist = Math.max.apply(null, weeks.map(function(w) { return w.metrics.derived_total_distance_km; })) || 1;
    var maxLoad = Math.max.apply(null, weeks.map(function(w) { return w.metrics.derived_training_load; })) || 1;
    var avgDist = weeks.reduce(function(s, w) { return s + w.metrics.derived_total_distance_km; }, 0) / weeks.length;

    var W = 400;
    var H = 260;
    var pad = { top: 16, right: 16, bottom: 40, left: 46 };
    var plotW = W - pad.left - pad.right;
    var plotH = H - pad.top - pad.bottom;
    var barW = plotW / weeks.length;
    var ns = "http://www.w3.org/2000/svg";

    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "chart-svg");
    svg.style.width = "100%";
    svg.style.minHeight = "260px";

    // Grid lines
    for (var g = 0; g <= 4; g++) {
      var gy = pad.top + plotH - (g / 4) * plotH;
      var gl = document.createElementNS(ns, "line");
      gl.setAttribute("x1", pad.left); gl.setAttribute("x2", W - pad.right);
      gl.setAttribute("y1", gy); gl.setAttribute("y2", gy);
      gl.setAttribute("class", "grid-line");
      svg.appendChild(gl);
    }

    // Load bars
    weeks.forEach(function(week, i) {
      var bx = pad.left + i * barW + barW * 0.15;
      var bw = barW * 0.7;
      var bh = (week.metrics.derived_training_load / maxLoad) * plotH;
      var by = pad.top + plotH - bh;
      var rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", bx); rect.setAttribute("y", by);
      rect.setAttribute("width", bw); rect.setAttribute("height", bh);
      rect.setAttribute("rx", "3");
      rect.setAttribute("class", "load-bar");
      svg.appendChild(rect);
    });

    // Distance line
    var points = weeks.map(function(week, i) {
      var x = pad.left + i * barW + barW / 2;
      var y = pad.top + plotH - (week.metrics.derived_total_distance_km / maxDist) * plotH;
      return x + "," + y;
    }).join(" ");
    var polyline = document.createElementNS(ns, "polyline");
    polyline.setAttribute("points", points);
    polyline.setAttribute("class", "distance-line");
    svg.appendChild(polyline);

    // Distance dots
    weeks.forEach(function(week, i) {
      var cx = pad.left + i * barW + barW / 2;
      var cy = pad.top + plotH - (week.metrics.derived_total_distance_km / maxDist) * plotH;
      var circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", cx); circle.setAttribute("cy", cy);
      circle.setAttribute("r", "4");
      circle.setAttribute("class", "distance-dot");
      svg.appendChild(circle);
    });

    // Average line (dashed)
    var avgY = pad.top + plotH - (avgDist / maxDist) * plotH;
    var avgLine = document.createElementNS(ns, "line");
    avgLine.setAttribute("x1", pad.left); avgLine.setAttribute("x2", W - pad.right);
    avgLine.setAttribute("y1", avgY); avgLine.setAttribute("y2", avgY);
    avgLine.setAttribute("stroke", "var(--muted)");
    avgLine.setAttribute("stroke-width", "1.5");
    avgLine.setAttribute("stroke-dasharray", "6 4");
    avgLine.setAttribute("opacity", "0.5");
    svg.appendChild(avgLine);

    // X labels
    weeks.forEach(function(week, i) {
      var tx = pad.left + i * barW + barW / 2;
      var label = document.createElementNS(ns, "text");
      label.setAttribute("x", tx); label.setAttribute("y", H - 8);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("class", "chart-label");
      label.textContent = week.week_start_label;
      svg.appendChild(label);
    });

    elements.weeklyChart.appendChild(svg);
  }

  function renderWeeklyNarratives(model) {
    var weeks = model.weekly_analysis.weeks;
    clear(elements.weeklyNarratives);

    weeks.forEach(function(week) {
      var card = document.createElement("div");
      card.className = "week-item";

      var top = document.createElement("div");
      top.className = "week-topline";
      top.appendChild(textElement("h4", "week-title", week.week_label));
      var quality = document.createElement("span");
      quality.className = "quality-pill" + (week.metrics.data_quality === "部分資料不足" ? " partial" : "");
      quality.textContent = week.metrics.data_quality;
      top.appendChild(quality);
      card.appendChild(top);

      var metrics = document.createElement("div");
      metrics.className = "week-metrics";
      [
        week.metrics.derived_total_distance_km + " km",
        week.metrics.derived_total_duration_min + " min",
        week.metrics.derived_training_load + " TSS"
      ].forEach(function(value) {
        metrics.appendChild(textElement("span", "", value));
      });
      card.appendChild(metrics);

      [
        { label: "觀察", text: week.key_observation },
        { label: "評估", text: week.weekly_assessment },
        { label: "建議", text: week.weekly_recommendation }
      ].forEach(function(block) {
        appendLabeledCopy(card, "week-copy", block.label, block.text);
      });

      if (week.risk_flags.length > 0) {
        var risks = document.createElement("div");
        risks.className = "risk-list";
        week.risk_flags.forEach(function(flag) {
          var tag = document.createElement("span");
          tag.className = "tag";
          tag.textContent = flag.label;
          risks.appendChild(tag);
        });
        card.appendChild(risks);
      }

      elements.weeklyNarratives.appendChild(card);
    });
  }

  function render12WeekTrend(model) {
    var trend = model.twelve_week_trend;
    clear(elements.twelveWeekContent);

    var grid = document.createElement("div");
    grid.className = "trend-12-grid";

    var summaryLead = document.createElement("div");
    summaryLead.className = "trend-summary-note";
    appendLabeledCopy(summaryLead, "", "總結", trend.summaryNote);
    elements.twelveWeekContent.appendChild(summaryLead);

    (trend.metrics || [
      { label: "跑量 (km)", value: "—", series: (trend.weeks || []).map(function(w) { return w.distance; }) },
      { label: "訓練負荷 (TSS)", value: "—", series: (trend.weeks || []).map(function(w) { return w.load; }) }
    ]).forEach(function(metric) {
      var card = document.createElement("div");
      card.className = "trend-metric-card";
      card.appendChild(textElement("span", "trend-metric-label", metric.label));
      card.appendChild(textElement("span", "trend-metric-value", metric.value));
      var sparkline = document.createElement("div");
      sparkline.className = "trend-sparkline";
      sparkline.innerHTML = renderSparkline(metric.series || []);
      card.appendChild(sparkline);
      grid.appendChild(card);
    });

    elements.twelveWeekContent.appendChild(grid);

    if (trend.temperature_note) {
      var temp = document.createElement("div");
      temp.className = "trend-summary-note";
      temp.appendChild(textElement("p", "", "🌡️ 高溫校正：" + trend.temperature_note));
      elements.twelveWeekContent.appendChild(temp);
    }
  }

  function renderSparkline(values) {
    if (!values || !values.length) {
      return "";
    }

    var max = Math.max.apply(null, values) || 1;
    var width = 100;
    var height = 50;
    var step = values.length > 1 ? width / (values.length - 1) : 0;
    
    var points = values.map(function(v, i) {
      return (i * step) + "," + (height - (v / max) * height);
    }).join(" ");

    return '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none">' +
           '<polyline fill="none" stroke="var(--blue)" stroke-width="3" points="' + points + '" />' +
           '</svg>';
  }

  function renderPlanSummary(plan) {
    if (!elements.planSummary) {
      return;
    }

    clear(elements.planSummary);
    var theme = document.createElement("span");
    theme.className = "plan-summary-theme";
    theme.textContent = plan.theme || "下週課表";

    var stats = document.createElement("span");
    stats.className = "plan-summary-stats";
    var statParts = [];
    if (plan.target_training_load) {
      statParts.push("目標週負荷 " + plan.target_training_load);
    }
    statParts.push("總跑量 " + plan.total_distance_km + "km");
    stats.textContent = statParts.join(" · ");

    elements.planSummary.appendChild(theme);
    elements.planSummary.appendChild(stats);

    if (elements.planAdjustment) {
      if (plan.adjustment_rule) {
        elements.planAdjustment.textContent = "⚠️ " + plan.adjustment_rule;
        elements.planAdjustment.classList.remove("hidden");
      } else {
        elements.planAdjustment.textContent = "";
        elements.planAdjustment.classList.add("hidden");
      }
    }
  }

  function buildPlanKeyCard(day) {
    var card = document.createElement("article");
    card.className = "plan-key-card";

    var eyebrow = document.createElement("p");
    eyebrow.className = "plan-key-eyebrow";
    eyebrow.textContent = day.day_label + " · " + day.session_type_label;

    var title = document.createElement("h4");
    title.className = "calendar-title";
    title.textContent = day.title;

    var detailParts = [];
    if (day.interval_label) {
      detailParts.push(day.interval_label);
    }
    if (day.pace_label) {
      detailParts.push("配速 " + day.pace_label);
    }
    if (day.rest_label) {
      detailParts.push("休 " + day.rest_label);
    }
    if (!detailParts.length) {
      detailParts.push((day.distance_km ? day.distance_km + "km · " : "") + day.duration_min + "min");
    }

    var detail = document.createElement("p");
    detail.className = "plan-key-detail";
    detail.textContent = detailParts.join(" · ");

    var intensity = document.createElement("p");
    intensity.className = "plan-key-intensity";
    intensity.textContent = day.intensity_label;

    card.appendChild(eyebrow);
    card.appendChild(title);
    card.appendChild(detail);
    card.appendChild(intensity);
    return card;
  }

  function renderCalendar(model) {
    var plan = model.next_week_plan;
    renderPlanSummary(plan);
    clear(elements.weeklyCalendar);

    var keySection = document.createElement("div");
    keySection.className = "plan-key-section";
    keySection.appendChild(textElement("p", "plan-section-label", "核心訓練"));
    var keyGrid = document.createElement("div");
    keyGrid.className = "plan-key-grid";

    var supportSection = document.createElement("div");
    supportSection.className = "plan-support-section";
    supportSection.appendChild(textElement("p", "plan-section-label", "輔助與恢復"));
    var supportRow = document.createElement("div");
    supportRow.className = "plan-support-row";

    plan.days.forEach(function(day) {
      if ((day.key_workout || day.intensity === 'hard') && day.intensity !== 'rest') {
        keyGrid.appendChild(buildPlanKeyCard(day));
      } else {
        var pill = document.createElement("div");
        pill.className = "plan-support-pill";
        pill.textContent = day.day_label + " " + day.session_type_label;
        supportRow.appendChild(pill);
      }
    });

    keySection.appendChild(keyGrid);
    supportSection.appendChild(supportRow);
    elements.weeklyCalendar.appendChild(keySection);
    elements.weeklyCalendar.appendChild(supportSection);
  }

  function renderZoneDistribution(target, title, distribution) {
    if (!target) {
      return;
    }

    var block = document.createElement("div");
    block.className = "intensity-block";

    var heading = document.createElement("h3");
    heading.className = "intensity-block-title";
    heading.textContent = title;
    block.appendChild(heading);

    if (!distribution || !distribution.has_data) {
      var empty = document.createElement("p");
      empty.className = "subtle";
      empty.textContent = "資料不足";
      block.appendChild(empty);
      target.appendChild(block);
      return;
    }

    var bar = document.createElement("div");
    bar.className = "hr-zone-bar";
    distribution.zones.forEach(function(zone) {
      if (zone.percentage > 0) {
        var segment = document.createElement("div");
        segment.style.width = zone.percentage + "%";
        segment.style.backgroundColor = zone.color;
        segment.title = zone.name + ": " + zone.percentage + "%";
        bar.appendChild(segment);
      }
    });
    block.appendChild(bar);

    var list = document.createElement("ul");
    list.className = "zone-list";
    distribution.zones.forEach(function(zone) {
      var li = document.createElement("li");
      var dot = document.createElement("span");
      dot.className = "zone-color";
      dot.style.background = zone.color;
      li.appendChild(dot);
      li.appendChild(textElement("span", "zone-name", zone.name));
      li.appendChild(textElement("span", "zone-value", zone.percentage + "%"));
      list.appendChild(li);
    });
    block.appendChild(list);

    if (distribution.assessment) {
      var assessment = document.createElement("p");
      assessment.className = "zone-assessment subtle";
      assessment.textContent = distribution.assessment;
      block.appendChild(assessment);
    }

    if (distribution.recommendation) {
      var recommendation = document.createElement("p");
      recommendation.className = "zone-recommendation subtle";
      recommendation.textContent = distribution.recommendation;
      block.appendChild(recommendation);
    }

    target.appendChild(block);
  }

  function renderIntensityZones(model) {
    var target = elements.intensityZones || elements.hrZones;
    clear(target);
    renderZoneDistribution(target, "心率區間", model.hr_zones);
    renderZoneDistribution(target, "功率區間", model.power_zones);
  }

  function renderPhysioMetrics(model) {
    var physio = model.physio_metrics;
    clear(elements.physioMetrics);

    var grid = document.createElement("div");
    grid.className = "physio-summary-card";

    var items = [
      { label: "VO2max", value: physio.vo2max.value || "資料不足", unit: "" },
      { label: "乳酸閾值配速", value: physio.lactate_threshold.pace.value || "資料不足", unit: physio.lactate_threshold.pace.value && physio.lactate_threshold.pace.value.indexOf("/") === -1 ? "/km" : "" },
      { label: "最大心率", value: physio.max_heart_rate.value || "資料不足", unit: physio.max_heart_rate.value ? "bpm" : "" }
    ];

    items.forEach(function(item) {
      var div = document.createElement("div");
      div.className = "physio-summary-item";
      var label = document.createElement("span");
      label.className = "stat-label";
      label.textContent = item.label;
      var value = document.createElement("span");
      value.className = "stat-value";
      value.textContent = item.value;
      div.appendChild(label);
      div.appendChild(value);
      if (item.unit) {
        var unit = document.createElement("span");
        unit.className = "stat-unit";
        unit.textContent = item.unit;
        div.appendChild(unit);
      }
      grid.appendChild(div);
    });

    elements.physioMetrics.appendChild(grid);

    if (physio.has_pace_zones && physio.pace_zones.length > 0) {
      var tableWrap = document.createElement("div");
      tableWrap.className = "pace-zone-table-wrap";

      var tableTitle = document.createElement("h3");
      tableTitle.className = "pace-zone-table-title";
      tableTitle.textContent = "配速區間";
      tableWrap.appendChild(tableTitle);

      var table = document.createElement("table");
      table.className = "pace-zone-table";
      table.innerHTML = "<thead><tr><th>區間</th><th>配速</th><th>心率</th></tr></thead>";
      var tbody = document.createElement("tbody");

      physio.pace_zones.forEach(function(zone) {
        var row = document.createElement("tr");
        var hrLabel = "—";
        if (zone.hr_min !== null && zone.hr_max !== null) {
          hrLabel = zone.hr_min + "–" + zone.hr_max + " bpm";
        }
        var nameCell = document.createElement("td");
        nameCell.textContent = zone.name;
        var paceCell = document.createElement("td");
        paceCell.textContent = zone.pace_range;
        var hrCell = document.createElement("td");
        hrCell.textContent = hrLabel;
        row.appendChild(nameCell);
        row.appendChild(paceCell);
        row.appendChild(hrCell);
        tbody.appendChild(row);
      });

      table.appendChild(tbody);
      tableWrap.appendChild(table);
      elements.physioMetrics.appendChild(tableWrap);
    }
  }

  function renderSessionSplitsTable(segments) {
    if (!segments || !segments.length) {
      return null;
    }

    var wrap = document.createElement("div");
    wrap.className = "evidence-splits-wrap";

    var title = document.createElement("p");
    title.className = "evidence-splits-title";
    title.textContent = "分段明細";
    wrap.appendChild(title);

    var table = document.createElement("table");
    table.className = "evidence-splits-table";
    table.innerHTML = "<thead><tr><th>#</th><th>類型</th><th>距離</th><th>配速</th><th>心率</th><th>步頻</th><th>步幅</th><th>備註</th></tr></thead>";
    var tbody = document.createElement("tbody");

    segments.forEach(function(segment) {
      var row = document.createElement("tr");
      var cells = [
        String(segment.index),
        segment.segment_type_label || segment.segment_type || "—",
        segment.distance_km !== null ? segment.distance_km + " km" : "—",
        segment.avg_pace || "—",
        segment.avg_hr !== null ? String(segment.avg_hr) + " bpm" : "—",
        segment.cadence !== null ? String(segment.cadence) + " spm" : "—",
        segment.stride_length_m !== null ? String(segment.stride_length_m) + " m" : "—",
        segment.note || "—"
      ];
      cells.forEach(function(value) {
        var cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });
      tbody.appendChild(row);
    });

    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function renderRunningMechanics(model) {
    var mechanics = model.running_mechanics;
    clear(elements.runningMechanics);

    var grid = document.createElement("div");
    grid.className = "mechanic-grid";

    mechanics.metrics.forEach(function(m) {
      var div = document.createElement("div");
      div.className = "mechanic-item";
      div.appendChild(textElement("span", "stat-label", m.title));
      var valueWrap = document.createElement("span");
      valueWrap.className = "stat-value";
      valueWrap.appendChild(document.createTextNode(m.display_value + " "));
      valueWrap.appendChild(textElement("span", "stat-unit", m.unit));
      div.appendChild(valueWrap);
      grid.appendChild(div);
    });

    elements.runningMechanics.appendChild(grid);

    if (mechanics.filter_note) {
      var note = document.createElement("p");
      note.className = "mechanics-filter-note subtle";
      note.textContent = mechanics.filter_note;
      elements.runningMechanics.appendChild(note);
    }
  }

  function renderEvidenceLayer(model) {
    var evidence = model.evidence;
    clear(elements.evidenceLayer);

    if (!evidence.hasEvidence) {
      elements.evidenceLayer.appendChild(textElement("p", "subtle", evidence.fallbackMessage));
      return;
    }

    if (isDebugMode()) {
      document.body.classList.add("debug-mode");
    }

    var wrapper = document.createElement("details");
    wrapper.className = "evidence-wrapper";
    wrapper.open = false;
    wrapper.appendChild(textElement("summary", "", "展開 " + evidence.items.length + " 項 AI 建議依據"));

    evidence.items.forEach(function(item) {
      var card = document.createElement("article");
      card.className = "evidence-item" + (item.high_risk ? " high-risk" : "");

      var claim = document.createElement("p");
      claim.className = "evidence-claim";
      claim.textContent = item.claim;
      card.appendChild(claim);

      var badge = document.createElement("span");
      badge.className = "pill " + confidencePillClass(item.confidence);
      badge.textContent = "可信度 " + item.confidence + "%";
      card.appendChild(badge);

      var advanced = document.createElement("details");
      advanced.className = "evidence-advanced";
      advanced.appendChild(textElement("summary", "", "查看依據數據"));

      var narrative = document.createElement("p");
      narrative.className = "evidence-narrative";
      narrative.textContent = typeof Adapter.evidenceRunnerNarrative === "function"
        ? Adapter.evidenceRunnerNarrative(item)
        : "依據近期訓練與生理指標";
      advanced.appendChild(narrative);

      if (item.supporting_metrics.length > 0) {
        var table = document.createElement("table");
        table.className = "evidence-table";
        table.innerHTML = "<thead><tr><th>指標</th><th>數值</th><th>來源</th></tr></thead>";
        var tbody = document.createElement("tbody");
        item.supporting_metrics.forEach(function(metric) {
          var row = document.createElement("tr");
          var value = metric.display_value || metric.value || "資料不足";
          appendTableCells(row, [
            metric.label || metric.metric || "指標",
            value,
            metric.source_label || "資料來源"
          ], 1);
          tbody.appendChild(row);
          if (isDebugMode() && metric.source_path) {
            var debugRow = document.createElement("tr");
            debugRow.className = "evidence-debug-path";
            var debugCell = document.createElement("td");
            debugCell.colSpan = 3;
            debugCell.textContent = "資料來源：" + (metric.source_label || "資料來源");
            debugRow.appendChild(debugCell);
            debugRow.title = metric.source_path;
            tbody.appendChild(debugRow);
          }
        });
        table.appendChild(tbody);
        advanced.appendChild(table);
      }

      if (item.supporting_sessions.length > 0) {
        item.supporting_sessions.forEach(function(session) {
          var header = document.createElement("p");
          header.className = "evidence-session-header";
          header.textContent = (session.date || "日期不詳") + " · " +
            (session.type || "訓練") +
            (session.distance_km ? " · " + session.distance_km + "km" : "");
          advanced.appendChild(header);

          if (session.reason) {
            var reason = document.createElement("p");
            reason.className = "evidence-session-reason";
            reason.textContent = session.reason;
            advanced.appendChild(reason);
          }

          var splits = renderSessionSplitsTable(session.segments);
          if (splits) {
            advanced.appendChild(splits);
          }

          if (isDebugMode() && session.source_path) {
            var debug = document.createElement("p");
            debug.className = "evidence-debug-path";
            debug.textContent = "資料來源：" + (session.source_label || "訓練活動");
            debug.title = session.source_path;
            advanced.appendChild(debug);
          }
        });
      }

      card.appendChild(advanced);
      wrapper.appendChild(card);
    });

    elements.evidenceLayer.appendChild(wrapper);
  }

  function render(model) {
    renderPrimaryAction(model);
    renderStatusCards(model);
    renderCoachSummary(model);
    renderLoadAssessment(model);
    renderRaceReadiness(model);
    renderLatestActivity(model);
    renderWeeklyChart(model);
    renderWeeklyNarratives(model);
    render12WeekTrend(model);
    renderCalendar(model);
    renderIntensityZones(model);
    renderPhysioMetrics(model);
    renderRunningMechanics(model);
    renderEvidenceLayer(model);
  }

  function populateReportSelect(reports, latest) {
    clear(elements.reportSelect);
    reports.forEach(function addOption(report) {
      var option = document.createElement("option");
      option.value = report.file;
      var datePart = report.file.match(/\d{8}/);
      var display = datePart ? datePart[0].slice(0,4) + "/" + datePart[0].slice(4,6) + "/" + datePart[0].slice(6,8) : report.file;
      option.textContent = display + (report.is_latest ? " (最新)" : "");
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
      setStatus("找不到 JSON 報告。", true);
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
    setStatus("正在掃描報告...", false);
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
