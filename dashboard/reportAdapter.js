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
    recovery: "恢復",
    lap: "分段"
  };
  var HR_ZONE_COLORS = ["#2f9e44", "#0ca678", "#f59f00", "#f76707", "#e03131"];
  var POWER_ZONE_COLORS = ["#4dabf7", "#339af0", "#228be6", "#1c7ed6", "#1864ab"];
  var SOURCE_SECTION_LABELS = {
    deterministic_context: "訓練資料",
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
    evidence_links: "建議理由",
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
  var INTENSITY_FOCUS_LABELS = {
    heart_rate: "心率",
    power: "功率",
    pace: "配速",
    heat: "高溫",
    load: "負荷",
    intensity: "強度"
  };
  var PATH_SEGMENT_LABELS = {
    deterministic_context: "訓練資料",
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
    segments: "分段",
    weekly_analysis: "近期訓練",
    sessions: "活動",
    hr_zone_distribution: "強度分佈",
    zones: "心率區間",
    running_mechanics: "跑姿指標",
    cadence_avg: "平均步頻",
    ground_contact_ms: "平均觸地時間",
    vertical_oscillation_cm: "平均垂直振幅",
    stride_length_m: "平均步幅",
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
    session_counts: "活動分布",
    by_type: "依訓練類型",
    by_source_activity_type: "依原始活動類型",
    total: "總活動數",
    recommendation: "建議",
    assessment: "評估",
    running_economy_score: "跑步經濟性分數",
    distance_km: "距離",
    duration_min: "時間",
    training_load: "訓練負荷",
    avg_hr: "平均心率",
    avg_pace: "平均配速",
    avg_hr: "平均心率",
    cadence: "步頻",
    environment: "環境",
    estimated_temp_c: "氣溫",
    humidity_pct: "濕度",
    hr_impact: "心率影響",
    training_effect_aerobic: "有氧訓練效果",
    training_effect_anaerobic: "無氧訓練效果"
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

  function metricDisplayValue(value, unit) {
    var rawValue = fallbackText(value, "資料不足");
    var rawUnit = fallbackText(unit, "").trim();
    if (!rawUnit || rawValue === "資料不足") {
      return rawValue;
    }

    var normalizedValue = rawValue.toLowerCase().replace(/\s+/g, "");
    var normalizedUnit = rawUnit.toLowerCase().replace(/\s+/g, "");
    if (normalizedValue.slice(-normalizedUnit.length) === normalizedUnit) {
      return rawValue;
    }

    return rawValue + (rawUnit === "%" ? "" : " ") + rawUnit;
  }

  function riskFlagLabel(flag) {
    var key = fallbackText(flag, "");
    return RISK_FLAG_LABELS[key] || humanizeIdentifier(key) || "風險提醒";
  }

  function intensityFocusLabel(value) {
    var key = fallbackText(value, "");
    return INTENSITY_FOCUS_LABELS[key] || humanizeIdentifier(key) || "強度";
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

  function sessionSourceLabel(sourcePath, sourceSession) {
    var match = /^weekly_analysis\[(\d+)\]\.sessions\[(\d+)\]/.exec(fallbackText(sourcePath, ""));
    if (!match) {
      return sourcePathLabel(sourcePath);
    }

    var type = sourceSession && sourceSession.type;
    var typeLabel = SESSION_TYPE_LABELS[type] || "";
    var dateLabel = sourceSession && sourceSession.date ? formatDateLabel(sourceSession.date) : "";
    if (dateLabel || typeLabel) {
      return [dateLabel, typeLabel].filter(Boolean).join(" ");
    }
    return "第 " + String(Number(match[1]) + 1) + " 週第 " + String(Number(match[2]) + 1) + " 堂訓練";
  }

  function metricSourceLabel(sourcePath, report) {
    var raw = fallbackText(sourcePath, "");
    var sessionMatch = /^(weekly_analysis\[\d+\]\.sessions\[\d+\])(?:\.(.+))?$/.exec(raw);
    if (!sessionMatch) {
      return sourcePathLabel(raw);
    }

    var sourceSession = readJsonPath(report, sessionMatch[1]);
    var base = sessionSourceLabel(sessionMatch[1], sourceSession);
    if (!sessionMatch[2]) {
      return base;
    }

    var fieldLabel = sourcePathLabel(sessionMatch[2]);
    return base + " > " + fieldLabel;
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

  function parsePaceSeconds(paceValue) {
    var text = fallbackText(paceValue, "").replace(/\/km/gi, "").trim();
    if (!text || text === "資料不足") {
      return null;
    }

    var parts = text.split(":");
    if (parts.length !== 2) {
      return null;
    }

    var minutes = Number(parts[0]);
    var seconds = Number(parts[1]);
    if (!Number.isFinite(minutes) || !Number.isFinite(seconds)) {
      return null;
    }

    return minutes * 60 + seconds;
  }

  function normalizeStrideLength(value) {
    if (!isPresentNumber(value)) {
      return null;
    }

    var number = Number(value);
    return roundTo(number > 10 ? number / 100 : number, 2);
  }

  function segmentStrideLength(segment) {
    var direct = normalizeStrideLength(segment && (segment.stride_length_m || segment.stride_length));
    if (direct !== null) {
      return direct;
    }

    var paceSeconds = parsePaceSeconds(segment && segment.avg_pace);
    var cadence = Number(segment && segment.cadence);
    if (!paceSeconds || !Number.isFinite(cadence) || cadence <= 0) {
      return null;
    }

    return roundTo(1000 / ((paceSeconds / 60) * cadence), 2);
  }

  function extractPlanWorkoutMeta(daySource) {
    var source = daySource || {};
    var description = fallbackText(source.description, "");
    var restType = normalizePlanRestType(source.rest_type || source.recovery_type || source.rest_mode);
    var restTime = formatPlanRestTime(source.rest_time || source.rest_seconds);
    var meta = {
      pace_label: fallbackText(source.target_pace || source.pace_target, ""),
      interval_label: fallbackText(source.interval_distance || source.rep_distance, ""),
      rest_label: [restType, restTime].filter(Boolean).join(" ")
    };

    if (!meta.pace_label) {
      var paceMatch = description.match(/(\d{1,2}:\d{2})(?:\s*[-–]\s*(\d{1,2}:\d{2}))?\s*\/\s*km/i)
        || description.match(/(\d{1,2}:\d{2})(?:\s*[-–]\s*(\d{1,2}:\d{2}))?/);
      if (paceMatch) {
        meta.pace_label = paceMatch[2] ? paceMatch[1] + "–" + paceMatch[2] + "/km" : paceMatch[1] + "/km";
      }
    }
    if (!meta.pace_label) {
      var repSecondsMatch = description.match(/配速\s*(\d{2,3})(?:\s*[-–]\s*(\d{2,3}))?\s*s/i)
        || description.match(/(\d{2,3})(?:\s*[-–]\s*(\d{2,3}))?\s*s\s*\/\s*(?:rep|趟|組)/i);
      if (repSecondsMatch) {
        meta.pace_label = repSecondsMatch[2]
          ? repSecondsMatch[1] + "–" + repSecondsMatch[2] + "s/rep"
          : repSecondsMatch[1] + "s/rep";
      }
    }

    if (!meta.interval_label) {
      var distanceFirstMatch = description.match(/(\d+(?:\.\d+)?)\s*m\s*[×x]\s*(\d+)/i);
      var countFirstMatch = description.match(/(\d+)\s*[×x]\s*(\d+(?:\.\d+)?)\s*m/i);
      if (distanceFirstMatch) {
        meta.interval_label = distanceFirstMatch[1] + "m × " + distanceFirstMatch[2];
      } else if (countFirstMatch) {
        meta.interval_label = countFirstMatch[2] + "m × " + countFirstMatch[1];
      }
    }

    if (!meta.rest_label) {
      var descriptionRestType = normalizePlanRestType(description);
      var restMatch = description.match(/(?:休息|間休|站休|跑休|走休|慢跑恢復|走路恢復|站著休息)\s*(\d+)\s*(?:s|秒)/i)
        || description.match(/rest\s*(\d+)\s*s/i);
      if (restMatch) {
        meta.rest_label = [descriptionRestType, restMatch[1] + "s"].filter(Boolean).join(" ");
      } else if (descriptionRestType) {
        meta.rest_label = descriptionRestType;
      }
    }

    return meta;
  }

  function formatPlanRestTime(value) {
    var text = fallbackText(value, "").trim();
    if (!text) {
      return "";
    }

    return /^\d+(?:\.\d+)?$/.test(text) ? text + "s" : text;
  }

  function normalizePlanRestType(value) {
    var text = fallbackText(value, "").toLowerCase();
    if (!text) {
      return "";
    }

    if (/站休|站著休息|原地休息|standing|stand/.test(text)) {
      return "站休";
    }
    if (/跑休|慢跑恢復|jogging|jog|running recovery/.test(text)) {
      return "跑休";
    }
    if (/走休|走路恢復|walking|walk/.test(text)) {
      return "走休";
    }
    return "";
  }

  function adaptWorkReps(session) {
    return safeArray(session && session.segments)
      .filter(function keepSegment(segment) {
        return Boolean(segment);
      })
      .map(function adaptRep(segment, index) {
        var segmentType = fallbackText(segment && segment.segment_type, "lap");
        return {
          index: index + 1,
          segment_type: segmentType,
          segment_type_label: SEGMENT_TYPE_LABELS[segmentType] || humanizeIdentifier(segmentType),
          distance_km: isPresentNumber(segment.distance_km) ? roundTo(segment.distance_km, 2) : null,
          avg_pace: segment.avg_pace || null,
          avg_hr: isPresentNumber(segment.avg_hr) ? roundTo(segment.avg_hr, 1) : null,
          cadence: isPresentNumber(segment.cadence) ? roundTo(segment.cadence, 1) : null,
          stride_length_m: segmentStrideLength(segment),
          note: fallbackText(segment.note, "")
        };
      });
  }

  function isFocusSession(session) {
    var type = fallbackText(session && session.type, "");
    return type === "interval" || type === "tempo" || type === "race" || type === "long";
  }

  function findLatestSession(report) {
    var latest = null;
    var latestFocus = null;
    safeArray(report.weekly_analysis).forEach(function scanWeek(week) {
      safeArray(week && week.sessions).forEach(function scanSession(session) {
        if (!session || !session.date) {
          return;
        }

        if (!latest || fallbackText(session.date, "").localeCompare(fallbackText(latest.date, "")) > 0) {
          latest = session;
        }

        if (isFocusSession(session) && (!latestFocus || fallbackText(session.date, "").localeCompare(fallbackText(latestFocus.date, "")) > 0)) {
          latestFocus = session;
        }
      });
    });
    return latestFocus || latest;
  }

  function buildLatestActivity(report) {
    var session = findLatestSession(report);
    if (!session) {
      return { has_data: false };
    }

    var adapted = adaptSession(session);
    var sessionType = adapted.type;
    var layout = sessionType === "interval" ? "interval" : sessionType === "long" ? "long" : sessionType === "race" ? "race" : "easy";
    var environment = session.environment || {};
    var workReps = adaptWorkReps(session);

    return {
      has_data: true,
      layout: layout,
      date_label: formatDateLabel(adapted.date),
      type_label: adapted.type_label,
      conclusion: fallbackText(session.coaching_note, ""),
      has_ai_conclusion: Boolean(fallbackText(session.coaching_note, "")),
      distance_km: adapted.distance_km,
      avg_pace: adapted.avg_pace || "--:--",
      avg_hr: adapted.avg_hr,
      temperature_c: isPresentNumber(environment.estimated_temp_c) ? roundTo(environment.estimated_temp_c, 1) : null,
      training_load: adapted.training_load,
      work_reps: workReps,
      coaching_notes: {
        observation: fallbackText(session.observation, ""),
        interpretation: fallbackText(session.interpretation, ""),
        recommendation: fallbackText(session.recommendation, "")
      }
    };
  }

  function buildPowerZones(report) {
    var distribution = report.power_zone_distribution || {};
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
        color: POWER_ZONE_COLORS[index],
        sourcePath: "power_zone_distribution.zones[" + String(index) + "]"
      };
    });

    return {
      period_weeks: distribution.period_weeks || null,
      zones: zones,
      assessment: fallbackText(distribution.assessment, ""),
      recommendation: fallbackText(distribution.recommendation, ""),
      has_data: zones.some(function hasMinutes(zone) {
        return zone.minutes > 0 || zone.percentage > 0;
      })
    };
  }

  function evidenceRunnerNarrative(item) {
    var session = safeArray(item.supporting_sessions)[0];
    if (session && session.date) {
      var typeLabel = SESSION_TYPE_LABELS[session.type] || session.type || "訓練";
      return "來自 " + formatDateLabel(session.date) + " " + typeLabel + " 的分段與環境資料";
    }

    var metric = safeArray(item.supporting_metrics)[0];
    if (metric && metric.label) {
      return "用「" + metric.label + "」等訓練數據判斷";
    }

    return "依據近期訓練與生理指標";
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
      return "快於 " + withPaceUnit(min);
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

  function formatDateRangeLabel(startDate, endDate) {
    var startLabel = startDate ? formatDateLabel(startDate) : "";
    var endLabel = endDate ? formatDateLabel(endDate) : "";

    if (startLabel && endLabel) {
      return startLabel + "-" + endLabel;
    }

    return startLabel || endLabel || "日期未設定";
  }

  function isoDateWithin(isoDate, startDate, endDate) {
    var date = parseIsoDate(isoDate);
    var start = parseIsoDate(startDate);
    var end = parseIsoDate(endDate);
    if (!date || !start || !end) {
      return false;
    }

    return date.getTime() >= start.getTime() && date.getTime() <= end.getTime();
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
    var runningDistance = 0;
    var swimDistance = 0;
    var bikeDistance = 0;
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

      if (session && session.type === "swim") {
        swimDistance += toNumber(session.distance_km);
      } else if (session && session.type === "bike") {
        bikeDistance += toNumber(session.distance_km);
      } else if (session && session.type !== "rest") {
        runningDistance += toNumber(session.distance_km);
      }
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
      derived_total_distance_km: roundTo(runningDistance, 2),
      derived_running_distance_km: roundTo(runningDistance, 2),
      derived_swim_distance_km: roundTo(swimDistance, 2),
      derived_bike_distance_km: roundTo(bikeDistance, 2),
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
      environment: session && session.environment ? session.environment : {},
      coaching_note: fallbackText(session && session.coaching_note, ""),
      segments: safeArray(session && session.segments)
    };
  }

  function adaptWeek(week, index) {
    var metrics = deriveWeeklyMetrics(week || {});
    var weekStart = week ? week.week_start : null;
    var adaptedSessions = safeArray(week && week.sessions).map(adaptSession);
    var explicitFocuses = safeArray(week && week.intensity_focuses).map(function adaptFocus(item) {
      if (typeof item === "string") {
        var text = item.trim();
        if (!text) {
          return null;
        }
        return {
          dimension: "intensity",
          label: intensityFocusLabel("intensity"),
          headline: "強度重點",
          analysis: text
        };
      }
      if (!item || typeof item !== "object") {
        return null;
      }

      var analysis = fallbackText(item.analysis || item.text, "").trim();
      if (!analysis) {
        return null;
      }
      var dimension = fallbackText(item.dimension, "intensity");
      return {
        dimension: dimension,
        label: intensityFocusLabel(dimension),
        headline: fallbackText(item.headline, "強度重點"),
        analysis: analysis
      };
    }).filter(Boolean).slice(0, 2);
    var intensityFocuses = explicitFocuses.length > 0
      ? explicitFocuses
      : buildFallbackIntensityFocuses(week, adaptedSessions, metrics);

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
      intensity_focuses: intensityFocuses,
      sessions: adaptedSessions,
      metrics: metrics
    };
  }

  function buildFallbackIntensityFocuses(week, sessions, metrics) {
    var focuses = [];
    var hottestTemp = null;
    var rankedSessions = sessions.filter(isFocusSession).map(function scoreSession(session) {
      var type = fallbackText(session.type, "easy");
      var typeWeight = type === "interval" ? 40
        : type === "race" ? 36
        : type === "tempo" ? 32
        : type === "long" ? 26
        : 12;
      var anaerobic = toNumber(session.training_effect_anaerobic) * 12;
      var aerobic = toNumber(session.training_effect_aerobic) * 7;
      var load = Math.min(toNumber(session.training_load), 120) * 0.25;
      return {
        session: session,
        score: typeWeight + anaerobic + aerobic + load
      };
    }).sort(function sortByScore(a, b) {
      if (b.score !== a.score) {
        return b.score - a.score;
      }
      return fallbackText(b.session.date, "").localeCompare(fallbackText(a.session.date, ""));
    });

    sessions.forEach(function inspectSession(session) {
      var temp = session.environment && session.environment.estimated_temp_c;
      if (isPresentNumber(temp) && (hottestTemp === null || Number(temp) > hottestTemp)) {
        hottestTemp = roundTo(temp, 1);
      }
    });

    if (safeArray(week && week.risk_flags).indexOf("heat_stress") !== -1 && hottestTemp !== null) {
      focuses.push({
        dimension: "heat",
        label: intensityFocusLabel("heat"),
        headline: "高溫放大心率反應",
        analysis: String(hottestTemp) + "°C 環境下，本週強度解讀要同時看體感與配速，不能只看心率高低。"
      });
    }

    rankedSessions.slice(0, 2).forEach(function addRepresentativeSession(item, index) {
      var session = item.session;
      var typeLabel = SESSION_TYPE_LABELS[session.type] || session.type || "訓練";
      var teParts = [];
      if (isPresentNumber(session.training_effect_anaerobic) && toNumber(session.training_effect_anaerobic) > 0) {
        teParts.push("無氧 TE " + roundTo(session.training_effect_anaerobic, 1));
      }
      if (isPresentNumber(session.training_effect_aerobic) && toNumber(session.training_effect_aerobic) > 0) {
        teParts.push("有氧 TE " + roundTo(session.training_effect_aerobic, 1));
      }
      if (isPresentNumber(session.training_load) && toNumber(session.training_load) > 0) {
        teParts.push("load " + roundTo(session.training_load, 1));
      }

      focuses.push({
        dimension: session.type === "interval" || session.type === "race" ? "pace" : "load",
        label: intensityFocusLabel(session.type === "interval" || session.type === "race" ? "pace" : "load"),
        headline: "代表課 " + String(index + 1) + "：" + formatDateLabel(session.date) + " " + typeLabel,
        analysis: teParts.length > 0
          ? teParts.join(" · ") + "，這堂課比單看平均心率更適合拿來判斷本週強度品質。"
          : "這堂課是本週最值得優先回看的強度課。"
      });
    });

    if (!focuses.length && metrics.derived_training_load > 0) {
      focuses.push({
        dimension: "load",
        label: intensityFocusLabel("load"),
        headline: "先看總負荷，再看區間比例",
        analysis: "本週累積 " + metrics.derived_training_load + " TSS，強度分佈應和總量一起解讀，避免單看某一個區間百分比。"
      });
    }

    return focuses.slice(0, 2);
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

  function crossTrainingAnalysis(session) {
    var sessionType = fallbackText(session && session.type, "");
    var sessionTypeLabel = SESSION_TYPE_LABELS[sessionType] || sessionType || "交叉訓練";
    var load = roundTo(session && session.training_load, 1);
    var aerobic = roundTo(session && session.training_effect_aerobic, 1);
    var anaerobic = roundTo(session && session.training_effect_anaerobic, 1);

    if (sessionType === "swim") {
      if (aerobic >= 3) {
        return "這堂游泳偏有氧刺激，可補容量又不額外增加跑步衝擊。";
      }
      return "這堂游泳以恢復和活動度維持為主，適合放在跑步主課之間。";
    }

    if (sessionType === "bike") {
      if (load >= 80 || aerobic >= 3 || anaerobic >= 2) {
        return "這堂單車負荷偏高，對心肺有幫助，但隔天跑步主課要留意腿部殘留疲勞。";
      }
      return "這堂單車主要扮演有氧補量，不應搶走跑步主課的恢復資源。";
    }

    return sessionTypeLabel + " 是本週負荷最高的交叉訓練，可當作跑步以外的補量刺激。";
  }

  function buildCrossTrainingHighlights(report) {
    return safeArray(report.weekly_analysis).map(function buildWeekHighlight(week, index) {
      var sessions = safeArray(week && week.sessions).map(adaptSession).filter(function keep(session) {
        return session.type === "swim" || session.type === "bike";
      });
      if (!sessions.length) {
        return null;
      }

      var picked = sessions.slice().sort(function sortByLoad(a, b) {
        var loadDiff = toNumber(b.training_load) - toNumber(a.training_load);
        if (loadDiff !== 0) {
          return loadDiff;
        }
        return fallbackText(b.date, "").localeCompare(fallbackText(a.date, ""));
      })[0];
      var aiFocus = week && week.cross_training_focus && typeof week.cross_training_focus === "object"
        ? week.cross_training_focus
        : {};
      var focusActivityId = fallbackText(aiFocus.activity_id, "").trim();
      var canUseAiFocus = !focusActivityId;
      if (focusActivityId) {
        var focusedSession = sessions.find(function matchesFocusActivity(session) {
          return fallbackText(session.activity_id, "").trim() === focusActivityId;
        });
        if (focusedSession) {
          picked = focusedSession;
          canUseAiFocus = true;
        }
      }
      var aiAnalysis = canUseAiFocus ? fallbackText(aiFocus.analysis, "").trim() : "";
      var aiHeadline = canUseAiFocus ? fallbackText(aiFocus.headline, "").trim() : "";

      return {
        week_index: index,
        week_label: fallbackText(week && week.week_label, "第" + String(index + 1) + "週"),
        session_type: picked.type,
        session_type_label: picked.type_label,
        title: aiHeadline || formatDateLabel(picked.date) + " " + picked.type_label,
        session_label: formatDateLabel(picked.date) + " " + picked.type_label,
        distance_label: picked.distance_km !== null && picked.distance_km > 0 ? picked.distance_km + " km" : "",
        duration_label: picked.duration_min !== null && picked.duration_min > 0 ? picked.duration_min + " min" : "",
        load_label: picked.training_load !== null && picked.training_load > 0 ? picked.training_load + " TSS" : "",
        analysis: aiAnalysis || crossTrainingAnalysis(picked),
        has_ai_analysis: Boolean(aiAnalysis)
      };
    }).filter(Boolean);
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
          unit: fallbackText(lactate.pace && lactate.pace.unit, "/km"),
          assessment: ""
        },
        assessment: fallbackText(lactate.assessment, "資料不足")
      },
      max_heart_rate: {
        value: metrics.max_heart_rate && isPresentNumber(metrics.max_heart_rate.value) ? metrics.max_heart_rate.value : null,
        unit: fallbackText(metrics.max_heart_rate && metrics.max_heart_rate.unit, "bpm")
      },
      resting_heart_rate: {
        value: metrics.resting_heart_rate && isPresentNumber(metrics.resting_heart_rate.value) ? metrics.resting_heart_rate.value : null,
        unit: fallbackText(metrics.resting_heart_rate && metrics.resting_heart_rate.unit, "bpm"),
        source: fallbackText(metrics.resting_heart_rate && metrics.resting_heart_rate.source, "")
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

      var workoutMeta = extractPlanWorkoutMeta(source);
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
        weather_consideration: fallbackText(source.weather_consideration, ""),
        pace_label: workoutMeta.pace_label,
        interval_label: workoutMeta.interval_label,
        rest_label: workoutMeta.rest_label
      });
    }

    var totalDistance = roundTo(days.reduce(function sumDistance(total, day) {
      return total + toNumber(day.distance_km);
    }, 0), 2);

    return {
      week_start: startDate,
      theme: fallbackText(plan.theme, "下週課表"),
      total_distance_km: totalDistance,
      target_training_load: isPresentNumber(plan.target_training_load)
        ? roundTo(plan.target_training_load, 1)
        : (isPresentNumber(plan.weekly_target_tss) ? roundTo(plan.weekly_target_tss, 1) : null),
      adjustment_rule: fallbackText(plan.adjustment_rule || plan.volume_adjustment_rule, ""),
      days: days,
      has_data: days.some(function hasWorkout(day) {
        return day.session_type !== "rest" || day.distance_km > 0 || day.duration_min > 0;
      })
    };
  }

  function metricWithFallback(metric, title, options) {
    var config = options || {};
    var value = metric && isPresentNumber(metric.value) ? metric.value : null;
    return {
      title: title,
      value: value,
      display_value: value === null ? "資料不足" : String(value),
      unit: fallbackText(metric && metric.unit, ""),
      assessment: config.showAssessment ? fallbackText(metric && metric.assessment, "資料不足") : "",
      has_data: value !== null
    };
  }

  function buildMechanics(report) {
    var mechanics = report.running_mechanics || {};
    var economy = isPresentNumber(mechanics.running_economy_score) ? clampScore(mechanics.running_economy_score) : null;

    return {
      metrics: [
        metricWithFallback(mechanics.cadence_avg, "步頻", { showAssessment: true }),
        metricWithFallback(mechanics.ground_contact_ms, "觸地時間"),
        metricWithFallback(mechanics.vertical_oscillation_cm, "垂直振幅"),
        metricWithFallback(mechanics.stride_length_m, "步幅")
      ],
      running_economy_score: economy,
      running_economy_label: economy === null ? "資料不足" : String(economy),
      improvement_tips: safeArray(mechanics.improvement_tips),
      filter_note: "已排除輕鬆跑與間歇休息段，僅計入有效跑步分圈。"
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
    var referenceDate = getPlanStartDate(report) || (report.meta && report.meta.today) || null;
    var phases = safeArray(periodization.phases).map(function adaptPhase(phase) {
      var startDate = phase.start_date || null;
      var endDate = phase.end_date || null;
      var isCurrent = referenceDate ? isoDateWithin(referenceDate, startDate, endDate) : false;
      var weeklyStructure = safeArray(phase.weekly_structure).map(function adaptStructure(session) {
        var intensity = fallbackText(session.intensity, "rest");
        var intensityMeta = INTENSITY_META[intensity] || { label: intensity, className: "intensity-unknown" };
        var sessionType = fallbackText(session.session_type, intensity === "rest" ? "rest" : "easy");
        var dayKey = normalizeDayKey(session.day, null);

        return {
          day_key: dayKey,
          day_label: DAY_LABELS_ZH[dayKey] || fallbackText(dayKey, "日期"),
          session_type: sessionType,
          session_type_label: SESSION_TYPE_LABELS[sessionType] || sessionType,
          description: fallbackText(session.description, ""),
          duration_min: isPresentNumber(session.duration_min) ? roundTo(session.duration_min, 1) : null,
          intensity: intensity,
          intensity_label: intensityMeta.label,
          intensity_class: intensityMeta.className
        };
      });

      return {
        phase_name: fallbackText(phase.phase_name, "未命名週期"),
        start_date: startDate,
        end_date: endDate,
        date_range_label: formatDateRangeLabel(startDate, endDate),
        weeks: isPresentNumber(phase.weeks) ? phase.weeks : null,
        weeks_label: isPresentNumber(phase.weeks) ? String(phase.weeks) + " 週" : "週數未設定",
        focus: fallbackText(phase.focus, ""),
        weekly_structure: weeklyStructure,
        is_current: isCurrent
      };
    });
    var currentPhase = phases.filter(function findCurrent(phase) {
      return phase.is_current;
    })[0] || null;

    return {
      weeks_to_race: isPresentNumber(periodization.weeks_to_race) ? periodization.weeks_to_race : null,
      weeks_to_race_label: isPresentNumber(periodization.weeks_to_race)
        ? "距離目標賽 " + periodization.weeks_to_race + " 週"
        : "目標賽週數未設定",
      reference_date: referenceDate,
      reference_date_label: referenceDate ? formatDateLabel(referenceDate) : "",
      phases: phases,
      current_phase: currentPhase,
      has_data: phases.length > 0
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
      "risk", "fatigue", "injury", "overtraining", "overreaching", "load", "疲勞", "風險", "傷", "疼痛", "過度", "中暑"
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
          copy.source_label = metricSourceLabel(sourcePath, report);
          copy.source_path = sourcePath;
          copy.display_value = metricDisplayValue(copy.value, copy.unit);
          return copy;
        }),
        supporting_sessions: safeArray(item && item.supporting_sessions).map(function adaptSupportingSession(session) {
          var sourcePath = session && session.source_path;
          var sourceSession = readJsonPath(report, sourcePath);
          var copy = {};
          Object.keys(session || {}).forEach(function copyKey(key) {
            copy[key] = session[key];
          });
          copy.date_label = copy.date ? formatDateLabel(copy.date) : "日期不詳";
          copy.type_label = SESSION_TYPE_LABELS[copy.type] || copy.type || "訓練";
          copy.distance_label = isPresentNumber(copy.distance_km) ? roundTo(copy.distance_km, 2) + " km" : "";
          copy.source_label = sessionSourceLabel(sourcePath, sourceSession);
          copy.source_path = sourcePath;
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
              stride_length_m: segmentStrideLength(segment),
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
      fallbackMessage: evidence.length > 0 ? "" : "此報告尚未提供教練判斷理由"
    };
  }

  function findEvidenceForText(text, evidenceItems) {
    var needle = fallbackText(text, "").toLowerCase();
    if (!needle) {
      return null;
    }

    var match = null;
    var bestScore = 0;

    safeArray(evidenceItems).forEach(function scoreEvidence(item) {
      var claim = fallbackText(item.claim, "").toLowerCase();
      if (!claim) {
        return;
      }

      var score = 0;

      // Exact substring match is strongest
      if (needle.indexOf(claim) !== -1 || claim.indexOf(needle) !== -1) {
        score = 20;
      } else {
        // Character bigram overlap for fuzzy matching
        var needleBigrams = {};
        var claimBigrams = {};
        var i;
        for (i = 0; i < needle.length - 1; i += 1) {
          var nb = needle.slice(i, i + 2);
          needleBigrams[nb] = (needleBigrams[nb] || 0) + 1;
        }
        for (i = 0; i < claim.length - 1; i += 1) {
          var cb = claim.slice(i, i + 2);
          claimBigrams[cb] = (claimBigrams[cb] || 0) + 1;
        }

        var overlap = 0;
        var total = 0;
        Object.keys(needleBigrams).forEach(function countOverlap(bigram) {
          total += needleBigrams[bigram];
          if (claimBigrams[bigram]) {
            overlap += Math.min(needleBigrams[bigram], claimBigrams[bigram]);
          }
        });

        if (total > 0) {
          score = (overlap / total) * 15;
        }
      }

      if (score > bestScore) {
        bestScore = score;
        match = item;
      }
    });

    return bestScore >= 3 ? match : null;
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

  function buildPrimaryAction(report) {
    var summary = report.coaching_summary || {};
    var status = report.athlete_status || {};
    var overall = status.overall_rating || {};
    
    var todayAction = safeArray(summary.top_3_actions)[0] || "依課表正常執行";
    var rationale = safeArray(summary.top_3_insights)[0] || "維持訓練節奏";
    
    return {
      todayAction: todayAction,
      rationale: rationale,
      statusBadge: fallbackText(overall.label, "狀態穩定"),
      statusClass: scoreState(clampScore(overall.score), false)
    };
  }

  function build12WeekTrend(report) {
    var dbTrend = report.db_fitness_trend || {};
    var rawTrend = safeArray(dbTrend.weeks).length ? safeArray(dbTrend.weeks) : safeArray(report.twelve_week_summary);

    var distancePoints = rawTrend.map(function mapDistance(week) {
      var value = toNumber(week.derived_total_distance_km);
      return {
        label: fallbackText(week.week_label, fallbackText(week.week_start, "週資料")),
        week_start_label: fallbackText(week.week_start, "").slice(5).replace("-", "/"),
        is_current_week: Boolean(week.is_current_week),
        week_progress_ratio: isPresentNumber(week.week_progress_ratio) ? Number(week.week_progress_ratio) : 1,
        value: value,
        display: String(value)
      };
    });
    var loadPoints = rawTrend.map(function mapLoad(week) {
      var value = toNumber(week.derived_training_load);
      return {
        label: fallbackText(week.week_label, fallbackText(week.week_start, "週資料")),
        week_start_label: fallbackText(week.week_start, "").slice(5).replace("-", "/"),
        is_current_week: Boolean(week.is_current_week),
        week_progress_ratio: isPresentNumber(week.week_progress_ratio) ? Number(week.week_progress_ratio) : 1,
        value: value,
        display: String(value)
      };
    });
    var distanceSeries = distancePoints.map(function(point) { return point.value; });
    var loadSeries = loadPoints.map(function(point) { return point.value; });

    var metrics = [
      {
        label: "12 週跑量",
        value: distanceSeries.length ? String(distanceSeries[distanceSeries.length - 1]) + " km" : "資料不足",
        unit: "km",
        points: distancePoints
      },
      {
        label: "12 週訓練量",
        value: loadSeries.length ? String(loadSeries[loadSeries.length - 1]) + " TSS" : "資料不足",
        unit: "TSS",
        points: loadPoints
      }
    ];

    return {
      metrics: metrics,
      periodLabel: rawTrend.length
        ? "近 12 週 · " + formatDateLabel(rawTrend[0].week_start) + " — " +
          formatDateLabel((report.meta && report.meta.today) || rawTrend[rawTrend.length - 1].week_start)
        : "",
      summaryNote: fallbackText(report.twelve_week_summary_note, ""),
      temperature_note: fallbackText(report.temperature_adjustment_note, "")
    };
  }

  function buildDashboardModel(report) {
    var source = report || {};
    var evidence = buildEvidence(source);

    return {
      meta: source.meta || {},
      status_cards: buildStatusCards(source),
      weekly_analysis: buildWeeklyAnalysis(source),
      cross_training_highlights: buildCrossTrainingHighlights(source),
      hr_zones: buildHrZones(source),
      power_zones: buildPowerZones(source),
      physio_metrics: buildPhysioMetrics(source),
      load_assessment: buildLoadAssessment(source),
      race_readiness: buildRaceReadiness(source),
      periodization: buildPeriodization(source),
      next_week_plan: buildCalendar(source),
      running_mechanics: buildMechanics(source),
      evidence: evidence,
      coaching_summary: buildCoachingSummary(source, evidence.items),
      primary_action: buildPrimaryAction(source),
      twelve_week_trend: build12WeekTrend(source),
      latest_activity: buildLatestActivity(source)
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
    sourcePathLabel: sourcePathLabel,
    metricDisplayValue: metricDisplayValue,
    evidenceRunnerNarrative: evidenceRunnerNarrative,
    parsePaceSeconds: parsePaceSeconds
  };
});
