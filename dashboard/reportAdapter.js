(function attachDashboardAdapter(root, factory) {
  var api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.DashboardAdapter = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createDashboardAdapter() {
  "use strict";

  var DAY_KEYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  var DAY_LABELS_ZH = {
    Mon: "週一",
    Tue: "週二",
    Wed: "週三",
    Thu: "週四",
    Fri: "週五",
    Sat: "週六",
    Sun: "週日"
  };
  var DAY_ALIASES = {
    MON: "Mon",
    MONDAY: "Mon",
    TUE: "Tue",
    TUESDAY: "Tue",
    WED: "Wed",
    WEDNESDAY: "Wed",
    THU: "Thu",
    THURSDAY: "Thu",
    FRI: "Fri",
    FRIDAY: "Fri",
    SAT: "Sat",
    SATURDAY: "Sat",
    SUN: "Sun",
    SUNDAY: "Sun"
  };
  var PRIORITY_ORDER = { high: 0, medium: 1, low: 2 };
  var INTENSITY_META = {
    easy: { label: "低強度", className: "intensity-easy" },
    moderate: { label: "中強度", className: "intensity-moderate" },
    hard: { label: "高強度", className: "intensity-hard" },
    rest: { label: "恢復", className: "intensity-rest" }
  };
  var SESSION_TYPE_LABELS = {
    easy: "輕鬆跑",
    tempo: "節奏跑",
    interval: "間歇",
    long: "長跑",
    race: "比賽",
    swim: "游泳",
    bike: "自行車",
    rest: "恢復"
  };
  var SEGMENT_TYPE_LABELS = {
    warmup: "熱身",
    main: "主課表",
    cooldown: "緩和",
    lap: "分段"
  };
  var HR_ZONE_COLORS = ["#2f9e44", "#0ca678", "#f59f00", "#f76707", "#e03131"];
  var SOURCE_SECTION_LABELS = {
    athlete_status: "目前狀態",
    physio_metrics: "生理指標",
    weekly_analysis: "近期訓練",
    hr_zone_distribution: "強度分佈",
    running_mechanics: "跑姿指標",
    load_assessment: "負荷評估",
    race_readiness: "目標能力",
    periodization: "週期化",
    next_week_plan: "課表建議",
    coaching_summary: "教練結論",
    evidence_links: "可追溯依據",
    pb_validation: "個人紀錄檢核",
    cross_training: "交叉訓練"
  };
  var VISUALIZATION_HINT_LABELS = {
    metric_card: "指標卡",
    session_list: "活動列表",
    chart_annotation: "圖表註記",
    calendar_badge: "課表提醒",
    table_row: "表格列"
  };
  var RISK_FLAG_LABELS = {
    heat_stress: "熱壓力",
    low_running_volume: "跑量偏低",
    overreaching_risk: "過度負荷風險",
    high_intensity_long_run: "長跑強度偏高",
    fatigue_risk: "疲勞風險",
    fatigue: "疲勞累積",
    low_volume: "訓練量偏低",
    injury_risk: "傷痛風險",
    overtraining: "過度訓練",
    undertraining: "訓練不足",
    high_intensity: "強度偏高",
    recovery_needed: "需要恢復"
  };
  var PATH_SEGMENT_LABELS = {
    athlete_status: "目前狀態",
    overall_rating: "整體狀態",
    fatigue_level: "疲勞程度",
    fitness_level: "體能狀態",
    physio_metrics: "生理指標",
    vo2max: "VO2max",
    lactate_threshold: "乳酸閾值",
    heart_rate: "心率",
    pace: "配速",
    max_heart_rate: "最大心率",
    resting_heart_rate: "靜息心率",
    pace_zones: "配速區間",
    weekly_analysis: "近期訓練",
    sessions: "活動",
    hr_zone_distribution: "強度分佈",
    zones: "心率區間",
    running_mechanics: "跑姿指標",
    load_assessment: "負荷評估",
    race_readiness: "目標能力",
    missing_capabilities: "能力缺口",
    next_week_plan: "課表建議",
    days: "課表日",
    periodization: "週期化",
    phases: "訓練階段",
    coaching_summary: "教練結論",
    score: "分數",
    label: "標籤",
    trend: "趨勢",
    percentage: "比例",
    minutes: "分鐘",
    confidence_score: "信心分數",
    training_suggestion: "訓練建議",
    current_tss_weekly: "本週 TSS",
    recommendation: "建議",
    assessment: "評估",
    running_economy_score: "跑步經濟性分數"
  };

  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object || {}, key);
  }

  function toNumber(value) {
    if (value === null || value === undefined || value === "") {
      return 0;
    }

    var number = Number(value);
    return Number.isFinite(number) ? number : 0;
  }

  function isPresentNumber(value) {
    if (value === null || value === undefined || value === "") {
      return false;
    }

    return Number.isFinite(Number(value));
  }

  function isMissingNumericField(object, key) {
    return !hasOwn(object, key) || !isPresentNumber(object[key]);
  }

  function roundTo(value, digits) {
    var factor = Math.pow(10, digits);
    return Math.round((toNumber(value) + Number.EPSILON) * factor) / factor;
  }

  function clampScore(value) {
    if (!isPresentNumber(value)) {
      return null;
    }

    return Math.max(0, Math.min(100, roundTo(value, 1)));
  }

  function fallbackText(value, fallback) {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }

    return String(value);
  }

  function humanizeIdentifier(value) {
    return fallbackText(value, "")
      .replace(/_/g, " ")
      .replace(/\b\w/g, function upper(match) {
        return match.toUpperCase();
      });
  }

  function sourceSectionLabel(section) {
    var key = fallbackText(section, "");
    return SOURCE_SECTION_LABELS[key] || humanizeIdentifier(key) || "資料來源";
  }

  function visualizationHintLabel(hint) {
    var key = fallbackText(hint, "");
    return VISUALIZATION_HINT_LABELS[key] || humanizeIdentifier(key) || "呈現方式";
  }

  function riskFlagLabel(flag) {
    var key = fallbackText(flag, "");
    return RISK_FLAG_LABELS[key] || humanizeIdentifier(key) || "風險提醒";
  }

  function sourcePathLabel(path) {
    var raw = fallbackText(path, "");
    if (!raw) {
      return "資料來源不足";
    }

    return raw.split(".").map(function labelSegment(segment) {
      var match = /^([A-Za-z_]+)(?:\[(\d+)\])?$/.exec(segment);
      if (!match) {
        return humanizeIdentifier(segment);
      }

      var name = PATH_SEGMENT_LABELS[match[1]] || sourceSectionLabel(match[1]);
      if (match[2] === undefined) {
        return name;
      }

      return name + " " + String(Number(match[2]) + 1);
    }).join(" > ");
  }

  function readJsonPath(root, path) {
    var current = root;
    var raw = fallbackText(path, "");
    if (!raw) {
      return null;
    }

    raw.split(".").some(function readSegment(segment) {
      var match = /^([A-Za-z_]+)(?:\[(\d+)\])?$/.exec(segment);
      if (!match || current === null || current === undefined) {
        current = null;
        return true;
      }

      current = current[match[1]];
      if (match[2] !== undefined && Array.isArray(current)) {
        current = current[Number(match[2])];
      } else if (match[2] !== undefined) {
        current = null;
        return true;
      }

      return false;
    });

    return current === undefined ? null : current;
  }

  function paceHasOpenEnd(value) {
    var normalized = fallbackText(value, "").replace(/\/km/g, "").trim();
    return normalized === "00:00" || normalized === "0:00";
  }

  function withPaceUnit(value) {
    var text = fallbackText(value, "");
    if (!text || text === "資料不足" || text.indexOf("/") !== -1) {
      return text;
    }

    return text + "/km";
  }

  function paceRangeLabel(paceMin, paceMax) {
    var min = fallbackText(paceMin, "");
    var max = fallbackText(paceMax, "");
    if (!min && !max) {
      return "資料不足";
    }

    if (paceHasOpenEnd(max) && min) {
      return "快於 " + withPaceUnit(min);
    }

    if (paceHasOpenEnd(min) && max) {
      return "慢於 " + withPaceUnit(max);
    }

    if (!min) {
      return withPaceUnit(max);
    }

    if (!max) {
      return withPaceUnit(min);
    }

    return min + " - " + max;
  }

  function parseIsoDate(value) {
    if (typeof value !== "string") {
      return null;
    }

    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match) {
      return null;
    }

    return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  }

  function formatIsoDate(date) {
    var year = String(date.getUTCFullYear());
    var month = String(date.getUTCMonth() + 1).padStart(2, "0");
    var day = String(date.getUTCDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function addDays(isoDate, days) {
    var date = parseIsoDate(isoDate);
    if (!date) {
      return null;
    }

    date.setUTCDate(date.getUTCDate() + days);
    return formatIsoDate(date);
  }

  function dayKeyFromDate(isoDate) {
    var date = parseIsoDate(isoDate);
    if (!date) {
      return null;
    }

    var jsDay = date.getUTCDay();
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][jsDay];
  }

  function normalizeDayKey(value, isoDate) {
    var derived = dayKeyFromDate(isoDate);
    if (derived) {
      return derived;
    }

    var raw = fallbackText(value, "").trim();
    var upper = raw.toUpperCase();
    return DAY_ALIASES[upper] || raw || "";
  }

  function formatDateLabel(isoDate) {
    var date = parseIsoDate(isoDate);
    if (!date) {
      return fallbackText(isoDate, "日期不足");
    }

    return String(date.getUTCMonth() + 1) + "/" + String(date.getUTCDate());
  }

  function nextMondayAfter(isoDate) {
    var date = parseIsoDate(isoDate);
    if (!date) {
      return null;
    }

    var jsDay = date.getUTCDay();
    var offset = (8 - jsDay) % 7;
    if (offset === 0) {
      offset = 7;
    }

    date.setUTCDate(date.getUTCDate() + offset);
    return formatIsoDate(date);
  }

  function mondayOnOrBefore(isoDate) {
    var date = parseIsoDate(isoDate);
    if (!date) {
      return null;
    }

    var jsDay = date.getUTCDay();
    var offset = jsDay === 0 ? -6 : 1 - jsDay;
    date.setUTCDate(date.getUTCDate() + offset);
    return formatIsoDate(date);
  }

  function trendMeta(trend) {
    if (trend === "improving") {
      return { label: "改善中", symbol: "↗", className: "trend-improving" };
    }

    if (trend === "declining") {
      return { label: "下滑", symbol: "↘", className: "trend-declining" };
    }

    return { label: "穩定", symbol: "→", className: "trend-stable" };
  }

  function scoreState(score, inverse) {
    if (score === null) {
      return "unknown";
    }

    if (inverse) {
      if (score >= 70) {
        return "danger";
      }

      if (score >= 50) {
        return "warning";
      }

      return "good";
    }

    if (score >= 75) {
      return "good";
    }

    if (score >= 50) {
      return "warning";
    }

    return "danger";
  }

  function buildStatusCards(report) {
    var status = report.athlete_status || {};
    var readiness = report.race_readiness || {};
    var overall = status.overall_rating || {};
    var fatigue = status.fatigue_level || {};
    var fitness = status.fitness_level || {};
    var trend = trendMeta(overall.trend);

    return [
      {
        key: "overall_rating",
        title: "整體狀態",
        score: clampScore(overall.score),
        label: fallbackText(overall.label, "資料不足"),
        trend: trend,
        state: scoreState(clampScore(overall.score), false),
        sourcePath: "athlete_status.overall_rating"
      },
      {
        key: "fatigue_level",
        title: "疲勞",
        score: clampScore(fatigue.score),
        label: fallbackText(fatigue.label, "資料不足"),
        trend: { label: "越低越好", symbol: "", className: "trend-neutral" },
        state: scoreState(clampScore(fatigue.score), true),
        sourcePath: "athlete_status.fatigue_level"
      },
      {
        key: "fitness_level",
        title: "體能",
        score: clampScore(fitness.score),
        label: fallbackText(fitness.label, "資料不足"),
        trend: { label: "體能基線", symbol: "", className: "trend-neutral" },
        state: scoreState(clampScore(fitness.score), false),
        sourcePath: "athlete_status.fitness_level"
      },
      {
        key: "race_readiness",
        title: "賽事準備度",
        score: clampScore(readiness.confidence_score),
        label: fallbackText(readiness.confidence_label, "資料不足"),
        trend: { label: fallbackText(readiness.race_name, "目標賽事"), symbol: "", className: "trend-neutral" },
        state: scoreState(clampScore(readiness.confidence_score), false),
        sourcePath: "race_readiness.confidence_score"
      }
    ];
  }

  function deriveWeeklyMetrics(week) {
    var sessions = safeArray(week && week.sessions);
    var distance = 0;
    var duration = 0;
    var load = 0;
    var missingFields = {};

    sessions.forEach(function addSession(session) {
      if (isMissingNumericField(session, "distance_km")) {
        missingFields.distance_km = true;
      }

      if (isMissingNumericField(session, "duration_min")) {
        missingFields.duration_min = true;
      }

      if (isMissingNumericField(session, "training_load")) {
        missingFields.training_load = true;
      }

      distance += toNumber(session && session.distance_km);
      duration += toNumber(session && session.duration_min);
      load += toNumber(session && session.training_load);
    });

    var missingFieldNames = Object.keys(missingFields);
    var qualityStatus = "完整";
    if (sessions.length === 0) {
      qualityStatus = "無訓練紀錄";
    } else if (missingFieldNames.length > 0) {
      qualityStatus = "部分資料不足";
    }

    return {
      derived_total_distance_km: roundTo(distance, 2),
      derived_total_duration_min: roundTo(duration, 1),
      derived_training_load: roundTo(load, 1),
      data_quality: qualityStatus,
      missing_fields: missingFieldNames,
      sessions_count: sessions.length
    };
  }

  function adaptSession(session) {
    var type = fallbackText(session && session.type, "rest");
    return {
      activity_id: session ? session.activity_id : null,
      date: session ? session.date : null,
      type: type,
      type_label: SESSION_TYPE_LABELS[type] || type,
      distance_km: isPresentNumber(session && session.distance_km) ? roundTo(session.distance_km, 2) : null,
      duration_min: isPresentNumber(session && session.duration_min) ? roundTo(session.duration_min, 1) : null,
      training_load: isPresentNumber(session && session.training_load) ? roundTo(session.training_load, 1) : null,
      avg_hr: isPresentNumber(session && session.avg_hr) ? roundTo(session.avg_hr, 1) : null,
      avg_pace: session ? session.avg_pace : null,
      training_effect_aerobic: session ? session.training_effect_aerobic : null,
      training_effect_anaerobic: session ? session.training_effect_anaerobic : null,
      coaching_note: fallbackText(session && session.coaching_note, "")
    };
  }

  function adaptWeek(week, index) {
    var metrics = deriveWeeklyMetrics(week || {});
    var weekStart = week ? week.week_start : null;

    return {
      index: index,
      week_label: fallbackText(week && week.week_label, "第" + String(index + 1) + "週"),
      week_start: weekStart,
      week_start_label: formatDateLabel(weekStart),
      key_observation: fallbackText(week && week.key_observation, "此週尚無 AI 觀察。"),
      weekly_assessment: fallbackText(week && week.weekly_assessment, "此週資料不足。"),
      weekly_recommendation: fallbackText(week && week.weekly_recommendation, "暫無建議。"),
      risk_flags: safeArray(week && week.risk_flags).map(function adaptRiskFlag(flag) {
        return {
          code: fallbackText(flag, ""),
          label: riskFlagLabel(flag)
        };
      }),
      sessions: safeArray(week && week.sessions).map(adaptSession),
      metrics: metrics
    };
  }

  function buildWeeklyAnalysis(report) {
    var weeks = safeArray(report.weekly_analysis).map(adaptWeek);
    var chronological = weeks.slice().sort(function sortByDate(a, b) {
      return fallbackText(a.week_start, "").localeCompare(fallbackText(b.week_start, ""));
    });

    return {
      weeks: weeks,
      chronological: chronological
    };
  }

  function buildHrZones(report) {
    var distribution = report.hr_zone_distribution || {};
    var zonesByNumber = {};
    safeArray(distribution.zones).forEach(function mapZone(zone) {
      if (zone && isPresentNumber(zone.zone)) {
        zonesByNumber[Number(zone.zone)] = zone;
      }
    });

    var zones = [1, 2, 3, 4, 5].map(function normalizeZone(zoneNumber, index) {
      var zone = zonesByNumber[zoneNumber] || {};
      return {
        zone: zoneNumber,
        name: fallbackText(zone.name, "Z" + String(zoneNumber)),
        minutes: roundTo(zone.minutes, 1),
        percentage: roundTo(zone.percentage, 1),
        color: HR_ZONE_COLORS[index],
        sourcePath: "hr_zone_distribution.zones[" + String(index) + "]"
      };
    });

    return {
      period_weeks: distribution.period_weeks || null,
      zones: zones,
      total_minutes: roundTo(zones.reduce(function sum(total, zone) {
        return total + toNumber(zone.minutes);
      }, 0), 1),
      assessment: fallbackText(distribution.assessment, "心率區間資料不足。"),
      is_polarized: Boolean(distribution.is_polarized),
      recommendation: fallbackText(distribution.recommendation, "暫無心率區間建議。"),
      has_data: zones.some(function hasMinutes(zone) {
        return zone.minutes > 0 || zone.percentage > 0;
      })
    };
  }

  function buildPhysioMetrics(report) {
    var metrics = report.physio_metrics || {};
    var lactate = metrics.lactate_threshold || {};
    var paceZones = safeArray(metrics.pace_zones).slice().sort(function sortPaceZones(a, b) {
      return toNumber(a && a.zone) - toNumber(b && b.zone);
    }).map(function adaptPaceZone(zone) {
      return {
        zone: zone.zone,
        name: fallbackText(zone.name, "Zone " + String(zone.zone)),
        pace_min: fallbackText(zone.pace_min, "資料不足"),
        pace_max: fallbackText(zone.pace_max, "資料不足"),
        pace_range: paceRangeLabel(zone.pace_min, zone.pace_max),
        hr_min: isPresentNumber(zone.hr_min) ? zone.hr_min : null,
        hr_max: isPresentNumber(zone.hr_max) ? zone.hr_max : null,
        is_reasonable: zone.is_reasonable !== false,
        note: fallbackText(zone.note, "")
      };
    });

    return {
      vo2max: {
        value: metrics.vo2max && isPresentNumber(metrics.vo2max.value) ? metrics.vo2max.value : null,
        unit: fallbackText(metrics.vo2max && metrics.vo2max.unit, ""),
        assessment: fallbackText(metrics.vo2max && metrics.vo2max.assessment, "資料不足")
      },
      lactate_threshold: {
        heart_rate: {
          value: lactate.heart_rate && isPresentNumber(lactate.heart_rate.value) ? lactate.heart_rate.value : null,
          unit: fallbackText(lactate.heart_rate && lactate.heart_rate.unit, "bpm")
        },
        pace: {
          value: fallbackText(lactate.pace && lactate.pace.value, "資料不足"),
          unit: fallbackText(lactate.pace && lactate.pace.unit, "/km")
        },
        assessment: fallbackText(lactate.assessment, "資料不足")
      },
      max_heart_rate: {
        value: metrics.max_heart_rate && isPresentNumber(metrics.max_heart_rate.value) ? metrics.max_heart_rate.value : null,
        unit: fallbackText(metrics.max_heart_rate && metrics.max_heart_rate.unit, "bpm")
      },
      resting_heart_rate: {
        value: metrics.resting_heart_rate && isPresentNumber(metrics.resting_heart_rate.value) ? metrics.resting_heart_rate.value : null,
        unit: fallbackText(metrics.resting_heart_rate && metrics.resting_heart_rate.unit, "bpm")
      },
      pace_zones: paceZones,
      has_pace_zones: paceZones.length > 0
    };
  }

  function buildRaceReadiness(report) {
    var readiness = report.race_readiness || {};
    var capabilities = safeArray(readiness.missing_capabilities).slice().sort(function sortCapability(a, b) {
      var aKey = fallbackText(a && a.priority, "low");
      var bKey = fallbackText(b && b.priority, "low");
      var aPriority = hasOwn(PRIORITY_ORDER, aKey) ? PRIORITY_ORDER[aKey] : 2;
      var bPriority = hasOwn(PRIORITY_ORDER, bKey) ? PRIORITY_ORDER[bKey] : 2;
      return aPriority - bPriority;
    }).map(function adaptCapability(item) {
      var priority = fallbackText(item.priority, "low");
      return {
        capability: fallbackText(item.capability, "能力缺口"),
        priority: priority,
        priority_label: priority === "high" ? "高優先" : priority === "medium" ? "中優先" : "低優先",
        training_suggestion: fallbackText(item.training_suggestion, "暫無訓練建議。")
      };
    });

    return {
      race_name: fallbackText(readiness.race_name, "目標賽事"),
      race_date: readiness.race_date || null,
      race_date_label: readiness.race_date ? readiness.race_date : "日期未設定",
      confidence_score: clampScore(readiness.confidence_score),
      confidence_label: fallbackText(readiness.confidence_label, "資料不足"),
      missing_capabilities: capabilities
    };
  }

  function getPlanStartDate(report) {
    var plan = report.next_week_plan || {};
    var days = safeArray(plan.days).slice().sort(function sortDays(a, b) {
      return fallbackText(a && a.date, "").localeCompare(fallbackText(b && b.date, ""));
    });

    if (plan.week_start) {
      return mondayOnOrBefore(plan.week_start) || plan.week_start;
    }

    if (days.length > 0 && days[0].date) {
      return mondayOnOrBefore(days[0].date) || days[0].date;
    }

    var currentWeekStart = report.weekly_analysis && report.weekly_analysis[0] && report.weekly_analysis[0].week_start;
    if (currentWeekStart) {
      return mondayOnOrBefore(addDays(currentWeekStart, 7)) || addDays(currentWeekStart, 7);
    }

    return nextMondayAfter(report.meta && report.meta.today) || null;
  }

  function buildCalendar(report) {
    var plan = report.next_week_plan || {};
    var startDate = getPlanStartDate(report);
    var byDate = {};
    safeArray(plan.days).forEach(function collectDay(day) {
      if (day && day.date) {
        byDate[day.date] = day;
      }
    });

    var days = [];
    for (var index = 0; index < 7; index += 1) {
      var date = startDate ? addDays(startDate, index) : null;
      var source = date ? byDate[date] || {} : {};
      var intensity = fallbackText(source.intensity, "rest");
      var intensityMeta = INTENSITY_META[intensity] || { label: intensity, className: "intensity-unknown" };
      var sessionType = fallbackText(source.session_type, intensity === "rest" ? "rest" : "easy");
      var dayKey = normalizeDayKey(source.day_of_week, date);

      days.push({
        date: date,
        date_label: formatDateLabel(date),
        day_key: dayKey,
        day_label: DAY_LABELS_ZH[dayKey] || fallbackText(dayKey, "日期"),
        session_type: sessionType,
        session_type_label: SESSION_TYPE_LABELS[sessionType] || sessionType,
        title: fallbackText(source.title, intensity === "rest" ? "恢復日" : "未命名課表"),
        description: fallbackText(source.description, ""),
        distance_km: roundTo(source.distance_km, 2),
        duration_min: roundTo(source.duration_min, 1),
        intensity: intensity,
        intensity_label: intensityMeta.label,
        intensity_class: intensityMeta.className,
        key_workout: Boolean(source.key_workout),
        weather_consideration: fallbackText(source.weather_consideration, "")
      });
    }

    return {
      week_start: startDate,
      theme: fallbackText(plan.theme, "下週課表"),
      total_distance_km: roundTo(days.reduce(function sumDistance(total, day) {
        return total + toNumber(day.distance_km);
      }, 0), 2),
      days: days,
      has_data: days.some(function hasWorkout(day) {
        return day.session_type !== "rest" || day.distance_km > 0 || day.duration_min > 0;
      })
    };
  }

  function metricWithFallback(metric, title) {
    var value = metric && isPresentNumber(metric.value) ? metric.value : null;
    return {
      title: title,
      value: value,
      display_value: value === null ? "資料不足" : String(value),
      unit: fallbackText(metric && metric.unit, ""),
      assessment: fallbackText(metric && metric.assessment, "資料不足"),
      has_data: value !== null
    };
  }

  function buildMechanics(report) {
    var mechanics = report.running_mechanics || {};
    var economy = isPresentNumber(mechanics.running_economy_score) ? clampScore(mechanics.running_economy_score) : null;

    return {
      metrics: [
        metricWithFallback(mechanics.cadence_avg, "步頻"),
        metricWithFallback(mechanics.ground_contact_ms, "觸地時間"),
        metricWithFallback(mechanics.vertical_oscillation_cm, "垂直振幅"),
        metricWithFallback(mechanics.stride_length_m, "步幅")
      ],
      running_economy_score: economy,
      running_economy_label: economy === null ? "資料不足" : String(economy),
      improvement_tips: safeArray(mechanics.improvement_tips)
    };
  }

  function buildLoadAssessment(report) {
    var load = report.load_assessment || {};
    return {
      current_tss_weekly: isPresentNumber(load.current_tss_weekly) ? roundTo(load.current_tss_weekly, 1) : null,
      optimal_tss_range: load.optimal_tss_range || null,
      status: fallbackText(load.status, "unknown"),
      label: fallbackText(load.label, "負荷資料不足"),
      recommendation: fallbackText(load.recommendation, "暫無負荷建議。")
    };
  }

  function buildPeriodization(report) {
    var periodization = report.periodization || {};
    return {
      weeks_to_race: isPresentNumber(periodization.weeks_to_race) ? periodization.weeks_to_race : null,
      phases: safeArray(periodization.phases).map(function adaptPhase(phase) {
        return {
          phase_name: fallbackText(phase.phase_name, "未命名週期"),
          start_date: phase.start_date || null,
          end_date: phase.end_date || null,
          weeks: isPresentNumber(phase.weeks) ? phase.weeks : null,
          focus: fallbackText(phase.focus, ""),
          weekly_structure: safeArray(phase.weekly_structure)
        };
      })
    };
  }

  function textBlob(value) {
    if (Array.isArray(value)) {
      return value.map(textBlob).join(" ");
    }

    if (value && typeof value === "object") {
      return Object.keys(value).map(function readKey(key) {
        return textBlob(value[key]);
      }).join(" ");
    }

    return fallbackText(value, "");
  }

  function isHighRiskEvidence(item) {
    var haystack = textBlob([
      item.insight_id,
      item.claim,
      item.source_sections,
      item.supporting_metrics,
      item.supporting_sessions
    ]).toLowerCase();
    var markers = [
      "risk",
      "fatigue",
      "injury",
      "overtraining",
      "overreaching",
      "load",
      "疲勞",
      "風險",
      "傷",
      "疼痛",
      "過度",
      "中暑"
    ];

    return markers.some(function containsMarker(marker) {
      return haystack.indexOf(marker) !== -1;
    });
  }

  function buildEvidence(report) {
    var evidence = safeArray(report.evidence_links).map(function adaptEvidence(item, index) {
      var confidence = clampScore(item && item.confidence);
      var visualizationHint = fallbackText(item && item.visualization_hint, "metric_card");
      var adapted = {
        id: fallbackText(item && item.insight_id, "evidence_" + String(index + 1)),
        claim: fallbackText(item && item.claim, "未命名依據"),
        source_sections: safeArray(item && item.source_sections),
        source_section_labels: safeArray(item && item.source_sections).map(sourceSectionLabel),
        supporting_metrics: safeArray(item && item.supporting_metrics).map(function adaptMetric(metric) {
          var sourcePath = metric && metric.source_path;
          var copy = {};
          Object.keys(metric || {}).forEach(function copyKey(key) {
            copy[key] = metric[key];
          });
          copy.source_label = sourcePathLabel(sourcePath);
          return copy;
        }),
        supporting_sessions: safeArray(item && item.supporting_sessions).map(function adaptSupportingSession(session) {
          var sourcePath = session && session.source_path;
          var sourceSession = readJsonPath(report, sourcePath);
          var copy = {};
          Object.keys(session || {}).forEach(function copyKey(key) {
            copy[key] = session[key];
          });
          copy.source_label = sourcePathLabel(sourcePath);
          copy.segments = safeArray(
            copy.segments && copy.segments.length ? copy.segments : sourceSession && sourceSession.segments
          ).map(function adaptSegment(segment, segmentIndex) {
            var segmentType = fallbackText(segment && segment.segment_type, "lap");
            return {
              index: segmentIndex + 1,
              segment_type: segmentType,
              segment_type_label: SEGMENT_TYPE_LABELS[segmentType] || humanizeIdentifier(segmentType),
              distance_km: isPresentNumber(segment && segment.distance_km) ? roundTo(segment.distance_km, 2) : null,
              avg_pace: segment ? segment.avg_pace : null,
              avg_hr: isPresentNumber(segment && segment.avg_hr) ? roundTo(segment.avg_hr, 1) : null,
              cadence: isPresentNumber(segment && segment.cadence) ? roundTo(segment.cadence, 1) : null,
              note: fallbackText(segment && segment.note, "")
            };
          });
          return copy;
        }),
        confidence: confidence === null ? 0 : confidence,
        visualization_hint: visualizationHint,
        visualization_label: visualizationHintLabel(visualizationHint),
        sourcePath: "evidence_links[" + String(index) + "]"
      };
      adapted.high_risk = isHighRiskEvidence(adapted);
      return adapted;
    }).sort(function sortEvidence(a, b) {
      if (a.high_risk !== b.high_risk) {
        return a.high_risk ? -1 : 1;
      }

      return b.confidence - a.confidence;
    });

    return {
      items: evidence,
      hasEvidence: evidence.length > 0,
      fallbackMessage: evidence.length > 0 ? "" : "此報告尚未提供可追溯依據"
    };
  }

  function normalizeForMatch(value) {
    return fallbackText(value, "").replace(/\s+/g, "").toLowerCase();
  }

  function evidenceSearchText(item) {
    return normalizeForMatch([
      item.id,
      item.claim,
      item.source_sections,
      item.supporting_metrics,
      item.supporting_sessions,
      item.visualization_hint
    ]);
  }

  function keywordTokens(value) {
    var normalized = normalizeForMatch(value);
    var knownTerms = [
      "疲勞",
      "風險",
      "強度",
      "高強度",
      "低強度",
      "恢復",
      "心率",
      "高區間",
      "長距離",
      "長跑",
      "跑量",
      "負荷",
      "配速",
      "目標配速",
      "1500",
      "vo2max",
      "間歇",
      "閾值",
      "有氧",
      "極化",
      "zone",
      "高溫",
      "補水",
      "防曬",
      "賽事",
      "能力",
      "交叉訓練",
      "自行車"
    ];
    var tokens = [];

    knownTerms.forEach(function addKnownTerm(term) {
      if (normalized.indexOf(term) !== -1) {
        tokens.push(term);
      }
    });

    fallbackText(value, "").toLowerCase().split(/[^\p{L}\p{N}]+/u).forEach(function addWord(word) {
      if (word.length >= 3) {
        tokens.push(word);
      }
    });

    return tokens.filter(function unique(token, index) {
      return token && tokens.indexOf(token) === index;
    });
  }

  function evidenceMatchScore(text, item) {
    var needle = normalizeForMatch(text);
    var haystack = evidenceSearchText(item);
    if (!needle || !haystack) {
      return 0;
    }

    var textPrefix = needle.slice(0, Math.min(12, needle.length));
    var claim = normalizeForMatch(item.claim);
    var claimPrefix = claim.slice(0, Math.min(12, claim.length));
    if (claim.indexOf(textPrefix) !== -1 || needle.indexOf(claimPrefix) !== -1) {
      return 100 + item.confidence / 100;
    }

    return keywordTokens(text).reduce(function countOverlap(score, token) {
      return haystack.indexOf(token) !== -1 ? score + 1 : score;
    }, 0) + item.confidence / 1000;
  }

  function findEvidenceForText(text, evidenceItems) {
    var match = null;
    var bestScore = 0;

    safeArray(evidenceItems).forEach(function scoreEvidence(item) {
      var score = evidenceMatchScore(text, item);
      if (score > bestScore) {
        bestScore = score;
        match = item;
      }
    });

    return bestScore >= 1 ? match : null;
  }

  function buildCoachingSummary(report, evidenceItems) {
    var summary = report.coaching_summary || {};
    var insights = safeArray(summary.top_3_insights).map(function adaptInsight(text) {
      var evidence = findEvidenceForText(text, evidenceItems);
      return {
        text: fallbackText(text, ""),
        evidence_id: evidence ? evidence.id : null
      };
    });
    var actions = safeArray(summary.top_3_actions).map(function adaptAction(text) {
      var evidence = findEvidenceForText(text, evidenceItems);
      return {
        text: fallbackText(text, ""),
        evidence_id: evidence ? evidence.id : null
      };
    });

    return {
      headline: fallbackText(summary.headline, "尚無教練摘要。"),
      top_3_insights: insights,
      top_3_actions: actions
    };
  }

  function buildDashboardModel(report) {
    var source = report || {};
    var evidence = buildEvidence(source);

    return {
      meta: source.meta || {},
      status_cards: buildStatusCards(source),
      weekly_analysis: buildWeeklyAnalysis(source),
      hr_zones: buildHrZones(source),
      physio_metrics: buildPhysioMetrics(source),
      load_assessment: buildLoadAssessment(source),
      race_readiness: buildRaceReadiness(source),
      periodization: buildPeriodization(source),
      next_week_plan: buildCalendar(source),
      running_mechanics: buildMechanics(source),
      evidence: evidence,
      coaching_summary: buildCoachingSummary(source, evidence.items)
    };
  }

  return {
    DAY_KEYS: DAY_KEYS,
    INTENSITY_META: INTENSITY_META,
    buildDashboardModel: buildDashboardModel,
    deriveWeeklyMetrics: deriveWeeklyMetrics,
    addDays: addDays,
    normalizeDayKey: normalizeDayKey,
    findEvidenceForText: findEvidenceForText,
    sourceSectionLabel: sourceSectionLabel,
    visualizationHintLabel: visualizationHintLabel,
    riskFlagLabel: riskFlagLabel,
    sourcePathLabel: sourcePathLabel
  };
});
