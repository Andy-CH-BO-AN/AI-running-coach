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
    crossTrainingHighlights: document.getElementById("crossTrainingHighlights"),
    twelveWeekContent: document.getElementById("twelveWeekContent"),
    weeklyCalendar: document.getElementById("weeklyCalendar"),
    planSummary: document.getElementById("planSummary"),
    planAdjustment: document.getElementById("planAdjustment"),
    periodizationOverview: document.getElementById("periodizationOverview"),
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
    title.textContent = primary.todayAction;
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
      trend.appendChild(textElement("summary", "", "split 比較"));

      var splitTable = renderSessionSplitsTable(latest.work_reps, "全部分段");
      if (splitTable) {
        trend.appendChild(splitTable);
        elements.latestActivity.appendChild(trend);
      }
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

    var table = document.createElement("table");
    table.className = "weekly-metrics-table";
    table.innerHTML = "<thead><tr><th>週期</th><th>跑量</th><th>訓練負荷</th><th>時間</th><th>資料狀態</th></tr></thead>";
    var tbody = document.createElement("tbody");
    weeks.forEach(function(week) {
      var row = document.createElement("tr");
      appendTableCells(row, [
        week.week_label,
        week.metrics.derived_running_distance_km + " km",
        week.metrics.derived_training_load + " TSS",
        week.metrics.derived_total_duration_min + " min",
        week.metrics.data_quality
      ], 0);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    elements.weeklyChart.appendChild(table);
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
      var metricLabels = [
        "跑步 " + week.metrics.derived_running_distance_km + " km"
      ];
      if (week.metrics.derived_swim_distance_km > 0) {
        metricLabels.push("游泳 " + week.metrics.derived_swim_distance_km + " km");
      }
      if (week.metrics.derived_bike_distance_km > 0) {
        metricLabels.push("單車 " + week.metrics.derived_bike_distance_km + " km");
      }
      metricLabels.push(week.metrics.derived_total_duration_min + " min");
      metricLabels.push(week.metrics.derived_training_load + " TSS");
      metricLabels.forEach(function(value) {
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

      if (week.intensity_focuses.length > 0) {
        var focusWrap = document.createElement("div");
        focusWrap.className = "week-focuses";
        focusWrap.appendChild(textElement("p", "week-focuses-title", "本週強度重點"));

        week.intensity_focuses.forEach(function(focus) {
          var item = document.createElement("div");
          item.className = "week-focus-item";

          var head = document.createElement("div");
          head.className = "week-focus-head";
          head.appendChild(textElement("span", "week-focus-pill", focus.label));
          head.appendChild(textElement("strong", "week-focus-headline", focus.headline));

          var body = document.createElement("p");
          body.className = "week-focus-text";
          body.textContent = focus.analysis;

          item.appendChild(head);
          item.appendChild(body);
          focusWrap.appendChild(item);
        });

        card.appendChild(focusWrap);
      }

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

  function renderCrossTrainingHighlights(model) {
    clear(elements.crossTrainingHighlights);
    if (!elements.crossTrainingHighlights) {
      return;
    }

    var highlights = model.cross_training_highlights || [];
    if (!highlights.length) {
      return;
    }

    highlights.forEach(function(highlight) {
      var card = document.createElement("article");
      card.className = "cross-training-card";

      var top = document.createElement("div");
      top.className = "cross-training-top";
      top.appendChild(textElement("h4", "cross-training-week", highlight.week_label));
      top.appendChild(textElement("span", "cross-training-type", highlight.session_type_label));
      card.appendChild(top);

      card.appendChild(textElement("p", "cross-training-title", highlight.title));
      if (highlight.has_ai_analysis && highlight.session_label && highlight.session_label !== highlight.title) {
        card.appendChild(textElement("p", "cross-training-session", highlight.session_label));
      }

      var stats = document.createElement("div");
      stats.className = "cross-training-metrics";
      [
        highlight.distance_label,
        highlight.duration_label,
        highlight.load_label
      ].forEach(function(value) {
        if (value) {
          stats.appendChild(textElement("span", "", value));
        }
      });
      card.appendChild(stats);

      card.appendChild(textElement("p", "cross-training-copy", highlight.analysis));
      elements.crossTrainingHighlights.appendChild(card);
    });
  }

  function render12WeekTrend(model) {
    var trend = model.twelve_week_trend;
    clear(elements.twelveWeekContent);

    if (trend.periodLabel) {
      elements.twelveWeekContent.appendChild(textElement("p", "trend-period-label", trend.periodLabel));
    }

    var grid = document.createElement("div");
    grid.className = "trend-summary-grid";

    if (trend.summaryNote) {
      var summaryLead = document.createElement("div");
      summaryLead.className = "trend-summary-note";
      appendLabeledCopy(summaryLead, "", "總結", trend.summaryNote);
      elements.twelveWeekContent.appendChild(summaryLead);
    }

    var metrics = trend.metrics || [
      { label: "跑量 (km)", value: "—", series: (trend.weeks || []).map(function(w) { return w.distance; }) },
      { label: "訓練負荷 (TSS)", value: "—", series: (trend.weeks || []).map(function(w) { return w.load; }) }
    ];

    var trendSeries = metrics.map(function(metric, index) {
      var points = normalizeTrendPoints(metric.points || metric.series || []);
      var displayMeta = metricTrendMeta(metric, index);
      return {
        metric: metric,
        index: index,
        mode: index === 0 ? "distance" : "load",
        points: points,
        meta: displayMeta,
        latest: points[points.length - 1] || { value: 0, display: "0" },
        peak: points.reduce(function findPeak(best, point) {
          return point.value > best.value ? point : best;
        }, points[0] || { value: 0, label: "資料不足", week_start_label: "" })
      };
    }).filter(function(series) {
      return series.points.length > 0;
    });

    if (!trendSeries.length) {
      elements.twelveWeekContent.appendChild(textElement("p", "empty-state", "近 12 週趨勢資料不足。"));
      return;
    }

    trendSeries.forEach(function(series) {
      var card = document.createElement("div");
      card.className = "trend-summary-card";

      var average = series.points.length
        ? series.points.reduce(function sum(total, point) { return total + point.value; }, 0) / series.points.length
        : 0;
      var expectedForWeek = series.latest.is_current_week ? average * series.latest.week_progress_ratio : average;
      var isLow = expectedForWeek > 0 && series.latest.value < expectedForWeek * 0.8;

      var summary = document.createElement("div");
      summary.className = "trend-card-summary";
      summary.appendChild(textElement("span", "trend-metric-label", series.index === 0 ? "本週跑量" : "本週訓練量"));
      var valueRow = document.createElement("div");
      valueRow.className = "trend-value-row";
      valueRow.appendChild(textElement("strong", "trend-metric-value", series.latest.display));
      valueRow.appendChild(textElement("span", "trend-unit", series.meta.unit));
      summary.appendChild(valueRow);

      var badgeRow = document.createElement("div");
      badgeRow.className = "trend-badge-row";
      var badgeText = series.latest.is_current_week
        ? (isLow ? "↓ 本週至今偏低" : "本週至今穩定")
        : (isLow ? "↓ 本週偏低" : "本週穩定");
      var badge = textElement("span", "trend-badge" + (isLow ? " low" : ""), badgeText);
      badgeRow.appendChild(badge);
      badgeRow.appendChild(textElement(
        "span",
        "trend-peak",
        "峰值 " + series.peak.display + " " + series.meta.unit + "（" + (series.peak.week_start_label || series.peak.label) + " 週）"
      ));
      summary.appendChild(badgeRow);

      card.appendChild(summary);
      grid.appendChild(card);
    });

    elements.twelveWeekContent.appendChild(grid);

    var chart = document.createElement("div");
    chart.className = "trend-chart shared";
    chart.appendChild(renderSharedTrendChart(trendSeries));
    trendSeries.forEach(function(series) {
      chart.appendChild(renderTrendDataTable(series.points, series.meta.unit, series.meta.label));
    });
    elements.twelveWeekContent.appendChild(chart);

    if (trend.temperature_note) {
      var temp = document.createElement("div");
      temp.className = "trend-summary-note";
      temp.appendChild(textElement("p", "", "高溫校正：" + trend.temperature_note));
      elements.twelveWeekContent.appendChild(temp);
    }
  }

  function normalizeTrendPoints(values) {
    return (values || []).map(function normalizePoint(point, index) {
      if (typeof point === "number") {
        return {
          label: "第 " + String(index + 1) + " 週",
          value: point,
          display: String(point),
          week_start_label: "",
          is_current_week: false,
          week_progress_ratio: 1
        };
      }
      return {
        label: point.label || ("第 " + String(index + 1) + " 週"),
        week_start_label: point.week_start_label || "",
        is_current_week: Boolean(point.is_current_week),
        week_progress_ratio: Number(point.week_progress_ratio) || 1,
        value: Number(point.value) || 0,
        display: point.display || String(point.value)
      };
    });
  }

  function metricTrendMeta(metric, index) {
    if (index === 0 || metric.unit === "km") {
      return { label: "週跑量", unit: "km" };
    }
    return { label: "週訓練量 TSS", unit: "TSS" };
  }

  function trendTickIndexes(points) {
    if (points.length <= 7) {
      return points.map(function(_, index) { return index; });
    }
    var indexes = [];
    for (var index = 0; index < points.length; index += 2) {
      indexes.push(index);
    }
    if (indexes[indexes.length - 1] !== points.length - 1) {
      if (points.length - 1 - indexes[indexes.length - 1] <= 1) {
        indexes.pop();
      }
      indexes.push(points.length - 1);
    }
    return indexes;
  }

  function renderSharedTrendChart(seriesList) {
    var ns = "http://www.w3.org/2000/svg";
    var wrapper = document.createElement("div");
    wrapper.className = "trend-chart-inner";
    var plot = document.createElement("div");
    plot.className = "trend-plot";

    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 100 64");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "trend-line-chart");

    var basePoints = seriesList[0] && seriesList[0].points ? seriesList[0].points : [];
    if (!basePoints.length) {
      plot.appendChild(svg);
      wrapper.appendChild(plot);
      return wrapper;
    }

    var xMin = 8;
    var xMax = 94;
    var chartMeta = [
      { mode: "distance", top: 4, height: 20, label: "週跑量 km", color: "var(--blue)" },
      { mode: "load", top: 33, height: 20, label: "週訓練量 TSS", color: "var(--green)" }
    ];
    var step = basePoints.length > 1 ? (xMax - xMin) / (basePoints.length - 1) : 0;

    chartMeta.forEach(function drawMeta(meta) {
      var axisLabel = textElement("span", "trend-chart-label", meta.label);
      axisLabel.style.top = (meta.top / 64 * 100) + "%";
      plot.appendChild(axisLabel);
    });

    seriesList.forEach(function drawSeries(series) {
      var meta = chartMeta[series.index] || chartMeta[0];
      var max = Math.max.apply(null, series.points.map(function(point) { return point.value; })) || 1;
      var pointPairs = series.points.map(function(point, index) {
        return {
          x: xMin + index * step,
          y: meta.top + meta.height - (point.value / max) * meta.height,
          point: point,
          index: index
        };
      });
      var points = pointPairs.map(function(pair) {
        return pair.x + "," + pair.y;
      }).join(" ");

      var polyline = document.createElementNS(ns, "polyline");
      polyline.setAttribute("fill", "none");
      polyline.setAttribute("stroke", meta.color);
      polyline.setAttribute("stroke-width", "2");
      polyline.setAttribute("vector-effect", "non-scaling-stroke");
      polyline.setAttribute("points", points);
      svg.appendChild(polyline);

      pointPairs.forEach(function(pair) {
        var hit = document.createElement("span");
        hit.className = "trend-hit-area " + series.mode;
        hit.style.left = pair.x + "%";
        hit.style.top = (pair.y / 64 * 100) + "%";
        hit.setAttribute("aria-hidden", "true");
        if (pair.x < 14) {
          hit.classList.add("edge-start");
        }
        if (pair.x > 90) {
          hit.classList.add("edge-end");
        }
        hit.appendChild(textElement(
          "span",
          "trend-tooltip " + series.mode,
          pair.point.label + " · " + pair.point.display + " " + series.meta.unit
        ));
        plot.appendChild(hit);

        var isPeak = pair.point === series.peak;
        var isLatest = pair.index === pointPairs.length - 1;
        if (!isPeak && !isLatest) {
          return;
        }

        var marker = document.createElement("span");
        marker.className = "trend-point " + series.mode + (isPeak ? " peak" : " latest");
        marker.style.left = pair.x + "%";
        marker.style.top = (pair.y / 64 * 100) + "%";
        plot.appendChild(marker);

        if (isPeak) {
          var label = textElement("span", "trend-peak-label " + series.mode, "peak " + pair.point.display);
          label.style.left = pair.x + "%";
          label.style.top = (pair.y / 64 * 100) + "%";
          if (pair.x < 14) {
            label.classList.add("edge-start");
          }
          if (pair.x > 90) {
            label.classList.add("edge-end");
          }
          label.textContent = "peak " + pair.point.display;
          plot.appendChild(label);
        }
      });
    });

    plot.appendChild(svg);
    wrapper.appendChild(plot);

    var axis = document.createElement("div");
    axis.className = "trend-axis";
    trendTickIndexes(basePoints).forEach(function(index) {
      var point = basePoints[index];
      var label = textElement("span", "trend-week-label", point.week_start_label || point.label);
      label.style.left = (xMin + index * step) + "%";
      axis.appendChild(label);
    });
    wrapper.appendChild(axis);

    wrapper.appendChild(textElement("p", "trend-source-label", "Garmin Connect · 每個資料點代表一週"));

    return wrapper;
  }

  function renderTrendDataTable(points, unit, label) {
    var table = document.createElement("table");
    table.className = "sr-only";
    table.innerHTML = "<caption>" + label + " 12 週資料</caption><thead><tr><th>週期</th><th>數值</th></tr></thead>";
    var tbody = document.createElement("tbody");
    points.forEach(function(point) {
      var row = document.createElement("tr");
      appendTableCells(row, [point.label, point.display + (unit ? " " + unit : "")], 0);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    return table;
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
        elements.planAdjustment.textContent = "注意：" + plan.adjustment_rule;
        elements.planAdjustment.classList.remove("hidden");
      } else {
        elements.planAdjustment.textContent = "";
        elements.planAdjustment.classList.add("hidden");
      }
    }
  }

  function buildPeriodizationStructureItem(item) {
    var row = document.createElement("li");
    row.className = "periodization-structure-item " + item.intensity_class;

    row.appendChild(textElement("span", "periodization-structure-day", item.day_label));
    row.appendChild(textElement("span", "periodization-structure-type", item.session_type_label));

    if (item.duration_min) {
      row.appendChild(textElement("span", "periodization-structure-duration", item.duration_min + "min"));
    }

    row.appendChild(textElement("span", "periodization-structure-intensity", item.intensity_label));

    if (item.description) {
      row.appendChild(textElement("span", "periodization-structure-copy", item.description));
    }

    return row;
  }

  function renderPeriodization(periodization) {
    if (!elements.periodizationOverview) {
      return;
    }

    clear(elements.periodizationOverview);
    if (!periodization || !periodization.has_data) {
      elements.periodizationOverview.hidden = true;
      return;
    }

    elements.periodizationOverview.hidden = false;

    var header = document.createElement("div");
    header.className = "periodization-header";
    var titleBlock = document.createElement("div");
    titleBlock.appendChild(textElement("p", "eyebrow", "週期化"));
    titleBlock.appendChild(textElement("h3", "periodization-title", "中長期訓練脈絡"));
    header.appendChild(titleBlock);
    header.appendChild(textElement("span", "periodization-race-label", periodization.weeks_to_race_label));
    elements.periodizationOverview.appendChild(header);

    var timeline = document.createElement("div");
    timeline.className = "periodization-timeline";
    periodization.phases.forEach(function appendPhase(phase) {
      var phaseNode = document.createElement("article");
      phaseNode.className = "periodization-phase" + (phase.is_current ? " is-current" : "");

      var top = document.createElement("div");
      top.className = "periodization-phase-top";
      top.appendChild(textElement("h4", "", phase.phase_name));
      top.appendChild(textElement("span", "", phase.date_range_label));
      phaseNode.appendChild(top);

      var meta = document.createElement("div");
      meta.className = "periodization-phase-meta";
      meta.appendChild(textElement("span", "", phase.weeks_label));
      if (phase.is_current) {
        meta.appendChild(textElement("span", "is-current-label", "目前階段"));
      }
      phaseNode.appendChild(meta);

      if (phase.focus) {
        phaseNode.appendChild(textElement("p", "periodization-focus", phase.focus));
      }

      timeline.appendChild(phaseNode);
    });
    elements.periodizationOverview.appendChild(timeline);

    if (periodization.current_phase && periodization.current_phase.weekly_structure.length) {
      var structure = document.createElement("div");
      structure.className = "periodization-structure";
      structure.appendChild(textElement("p", "plan-section-label", "目前階段週結構"));

      var list = document.createElement("ul");
      list.className = "periodization-structure-list";
      periodization.current_phase.weekly_structure.forEach(function appendStructure(item) {
        list.appendChild(buildPeriodizationStructureItem(item));
      });
      structure.appendChild(list);
      elements.periodizationOverview.appendChild(structure);
    }
  }

  function buildPlanKeyCard(day) {
    var card = document.createElement("article");
    card.className = "plan-day-card key";

    var eyebrow = document.createElement("p");
    eyebrow.className = "plan-key-eyebrow";
    eyebrow.textContent = day.day_label + " · " + day.date_label + " · " + day.session_type_label;

    var title = document.createElement("h4");
    title.className = "calendar-title";
    title.textContent = day.title;

    var detailParts = [];
    var volumeParts = [];
    if (day.distance_km) {
      volumeParts.push(day.distance_km + "km");
    }
    if (day.duration_min) {
      volumeParts.push(day.duration_min + "min");
    }
    if (volumeParts.length) {
      detailParts.push(volumeParts.join(" · "));
    }
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
    detailParts.forEach(function appendDetailPart(part) {
      detail.appendChild(textElement("span", "", part));
    });

    var intensity = document.createElement("p");
    intensity.className = "plan-key-intensity";
    intensity.textContent = day.intensity_label;

    if (day.description) {
      var description = document.createElement("p");
      description.className = "plan-day-copy";
      description.textContent = day.description;
      card.appendChild(eyebrow);
      card.appendChild(title);
      card.appendChild(detail);
      card.appendChild(intensity);
      card.appendChild(description);
      return card;
    }

    card.appendChild(eyebrow);
    card.appendChild(title);
    card.appendChild(detail);
    card.appendChild(intensity);
    return card;
  }

  function buildPlanSupportCard(day) {
    var card = document.createElement("article");
    card.className = "plan-day-card support " + day.intensity_class;

    var top = document.createElement("div");
    top.className = "calendar-date";
    top.appendChild(textElement("span", "", day.day_label));
    top.appendChild(textElement("span", "", day.date_label));

    var title = document.createElement("h4");
    title.className = "calendar-title";
    title.textContent = day.title;

    var meta = document.createElement("div");
    meta.className = "calendar-meta";
    meta.appendChild(textElement("span", "intensity-pill " + day.intensity_class, day.intensity_label));
    meta.appendChild(textElement("span", "intensity-pill", day.session_type_label));

    var volumeParts = [];
    if (day.distance_km) {
      volumeParts.push(day.distance_km + "km");
    }
    if (day.duration_min) {
      volumeParts.push(day.duration_min + "min");
    }
    if (volumeParts.length) {
      meta.appendChild(textElement("span", "intensity-pill", volumeParts.join(" · ")));
    }

    var copy = document.createElement("p");
    copy.className = "plan-day-copy";
    copy.textContent = day.description || day.weather_consideration || (day.intensity === "rest" ? "完整恢復，保留下一次品質課的體能。" : "輔助課表，控制強度並累積恢復品質。");

    card.appendChild(top);
    card.appendChild(title);
    card.appendChild(meta);
    card.appendChild(copy);

    if (day.weather_consideration && day.weather_consideration !== copy.textContent) {
      var weather = document.createElement("p");
      weather.className = "plan-day-note";
      weather.textContent = day.weather_consideration;
      card.appendChild(weather);
    }

    return card;
  }

  function renderCalendar(model) {
    var plan = model.next_week_plan;
    renderPlanSummary(plan);
    clear(elements.weeklyCalendar);
    elements.weeklyCalendar.classList.add("plan-layout");

    var keySection = document.createElement("div");
    keySection.className = "plan-key-section";
    keySection.appendChild(textElement("p", "plan-section-label", "核心訓練"));
    var keyGrid = document.createElement("div");
    keyGrid.className = "plan-key-grid";

    var supportSection = document.createElement("div");
    supportSection.className = "plan-support-section";
    supportSection.appendChild(textElement("p", "plan-section-label", "輔助與恢復"));
    var supportGrid = document.createElement("div");
    supportGrid.className = "plan-support-grid";

    plan.days.forEach(function(day) {
      if ((day.key_workout || day.intensity === 'hard') && day.intensity !== 'rest') {
        keyGrid.appendChild(buildPlanKeyCard(day));
      } else {
        supportGrid.appendChild(buildPlanSupportCard(day));
      }
    });

    if (!keyGrid.children.length) {
      keyGrid.appendChild(textElement("p", "empty-state compact", "本週沒有標記核心訓練。"));
    }

    keySection.appendChild(keyGrid);
    supportSection.appendChild(supportGrid);
    elements.weeklyCalendar.appendChild(keySection);
    elements.weeklyCalendar.appendChild(supportSection);
  }

  function renderZoneDistribution(target, title, distribution) {
    if (!target) {
      return;
    }

    var block = document.createElement("article");
    block.className = "zone-distribution-card";

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

    var list = document.createElement("div");
    list.className = "zone-row-list";
    distribution.zones.forEach(function(zone) {
      var row = document.createElement("div");
      row.className = "zone-row";

      var label = document.createElement("b");
      label.textContent = zone.name;

      var track = document.createElement("div");
      track.className = "zone-bar";
      var fill = document.createElement("span");
      fill.style.width = Math.max(0, Math.min(100, zone.percentage)) + "%";
      fill.style.backgroundColor = zone.color;
      track.appendChild(fill);

      var value = document.createElement("b");
      value.textContent = zone.percentage + "%";

      var dot = document.createElement("span");
      dot.className = "zone-dot";
      dot.style.background = zone.color;
      label.insertBefore(dot, label.firstChild);

      row.appendChild(label);
      row.appendChild(track);
      row.appendChild(value);
      list.appendChild(row);
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
    var grid = document.createElement("div");
    grid.className = "zone-card-grid";
    target.appendChild(grid);
    renderZoneDistribution(grid, "心率區間", model.hr_zones);
    renderZoneDistribution(grid, "功率區間", model.power_zones);
    renderPaceZoneCard(grid, model.physio_metrics);
  }

  function renderPaceZoneCard(target, physio) {
    var block = document.createElement("article");
    block.className = "zone-distribution-card";
    block.appendChild(textElement("h3", "intensity-block-title", "配速區間"));

    if (!physio || !physio.has_pace_zones || physio.pace_zones.length === 0) {
      block.appendChild(textElement("p", "subtle", "資料不足"));
      target.appendChild(block);
      return;
    }

    var table = document.createElement("table");
    table.className = "pace-zone-table compact";
    table.innerHTML = "<thead><tr><th>區間</th><th>配速</th><th>心率</th></tr></thead>";
    var tbody = document.createElement("tbody");
    physio.pace_zones.forEach(function(zone) {
      var row = document.createElement("tr");
      var hrLabel = "—";
      if (zone.hr_min !== null && zone.hr_max !== null) {
        hrLabel = zone.hr_min + "–" + zone.hr_max + " bpm";
      }
      appendTableCells(row, [zone.name, zone.pace_range, hrLabel], 0);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    block.appendChild(table);
    target.appendChild(block);
  }

  function renderPhysioMetrics(model) {
    var physio = model.physio_metrics;
    clear(elements.physioMetrics);

    var grid = document.createElement("div");
    grid.className = "metric-grid physio-metric-grid";

    var items = [
      { label: "VO2max", value: physio.vo2max.value || "資料不足", unit: "" },
      { label: "乳酸閾值配速", value: physio.lactate_threshold.pace.value || "資料不足", unit: physio.lactate_threshold.pace.value && physio.lactate_threshold.pace.value.indexOf("/") === -1 ? "/km" : "" },
      { label: "最大心率", value: physio.max_heart_rate.value || "資料不足", unit: physio.max_heart_rate.value ? "bpm" : "" },
      {
        label: physio.resting_heart_rate.source === "estimated_from_lowest_activity_avg_hr" ? "靜止心率(估)" : "靜止心率",
        value: physio.resting_heart_rate.value || "資料不足",
        unit: physio.resting_heart_rate.value ? "bpm" : ""
      }
    ];

    items.forEach(function(item) {
      var div = document.createElement("div");
      div.className = "metric-tile";
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
  }

  function renderSessionSplitsTable(segments, titleText) {
    if (!segments || !segments.length) {
      return null;
    }
    var showCadence = segments.some(function hasCadence(segment) {
      return segment && segment.cadence !== null && segment.cadence !== undefined;
    });
    var showStrideLength = segments.some(function hasStrideLength(segment) {
      return segment && segment.stride_length_m !== null && segment.stride_length_m !== undefined;
    });

    var wrap = document.createElement("div");
    wrap.className = "evidence-splits-wrap";

    var title = document.createElement("p");
    title.className = "evidence-splits-title";
    title.textContent = titleText || "分段明細";
    wrap.appendChild(title);

    var table = document.createElement("table");
    table.className = "evidence-splits-table";
    var thead = document.createElement("thead");
    var headerRow = document.createElement("tr");
    ["#", "類型", "距離", "配速", "心率"].forEach(function addHeader(label) {
      headerRow.appendChild(textElement("th", "", label));
    });
    if (showCadence) {
      headerRow.appendChild(textElement("th", "", "步頻"));
    }
    if (showStrideLength) {
      headerRow.appendChild(textElement("th", "", "步幅"));
    }
    headerRow.appendChild(textElement("th", "", "備註"));
    thead.appendChild(headerRow);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");

    segments.forEach(function(segment) {
      var row = document.createElement("tr");
      var cells = [
        String(segment.index),
        segment.segment_type_label || segment.segment_type || "—",
        segment.distance_km !== null ? segment.distance_km + " km" : "—",
        segment.avg_pace || "—",
        segment.avg_hr !== null ? String(segment.avg_hr) + " bpm" : "—"
      ];
      if (showCadence) {
        cells.push(segment.cadence !== null && segment.cadence !== undefined ? String(segment.cadence) + " spm" : "—");
      }
      if (showStrideLength) {
        cells.push(segment.stride_length_m !== null && segment.stride_length_m !== undefined ? String(segment.stride_length_m) + " m" : "—");
      }
      cells.push(segment.note || "—");
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

  function renderEvidenceMetricCard(metric) {
    var card = document.createElement("div");
    card.className = "evidence-metric-card";

    var label = document.createElement("p");
    label.className = "evidence-metric-label";
    label.textContent = metric.label || metric.metric || "指標";
    card.appendChild(label);

    var value = document.createElement("p");
    value.className = "evidence-metric-value";
    value.textContent = metric.display_value || metric.value || "資料不足";
    card.appendChild(value);

    return card;
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
    wrapper.appendChild(textElement("summary", "", "查看 " + evidence.items.length + " 項教練判斷理由"));

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
      advanced.appendChild(textElement("summary", "", "查看訓練數據"));

      if (item.supporting_sessions.length === 0) {
        var narrative = document.createElement("p");
        narrative.className = "evidence-narrative";
        narrative.textContent = typeof Adapter.evidenceRunnerNarrative === "function"
          ? Adapter.evidenceRunnerNarrative(item)
          : "依據近期訓練與生理指標";
        advanced.appendChild(narrative);
      }

      if (item.supporting_metrics.length > 0) {
        var metricGrid = document.createElement("div");
        metricGrid.className = "evidence-metric-grid" + (item.supporting_metrics.length === 1 ? " single-metric" : "");
        item.supporting_metrics.forEach(function(metric) {
          metricGrid.appendChild(renderEvidenceMetricCard(metric));
          if (isDebugMode() && metric.source_path) {
            var debug = document.createElement("p");
            debug.className = "evidence-debug-path";
            debug.textContent = "資料來源：" + (metric.source_label || "資料來源");
            debug.title = metric.source_path;
            metricGrid.appendChild(debug);
          }
        });
        advanced.appendChild(metricGrid);
      }

      if (item.supporting_sessions.length > 0) {
        item.supporting_sessions.forEach(function(session) {
          var header = document.createElement("p");
          header.className = "evidence-session-header";
          header.textContent = [
            session.date_label || "日期不詳",
            session.type_label || "訓練",
            session.distance_label || ""
          ].filter(Boolean).join(" · ");
          advanced.appendChild(header);

          if (session.reason) {
            var reason = document.createElement("div");
            reason.className = "evidence-session-reason";
            reason.appendChild(textElement("p", "", session.reason));
            advanced.appendChild(reason);
          }

          var splitCount = session.segments ? session.segments.length : 0;
          if (splitCount > 0) {
            var splitDetails = document.createElement("details");
            splitDetails.className = "evidence-session-splits";
            splitDetails.appendChild(textElement("summary", "", "查看 " + splitCount + " 筆分段"));
            var splits = renderSessionSplitsTable(session.segments, "全部分段");
            if (splits) {
              splitDetails.appendChild(splits);
              advanced.appendChild(splitDetails);
            }
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
    renderCrossTrainingHighlights(model);
    render12WeekTrend(model);
    renderPeriodization(model.periodization);
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
