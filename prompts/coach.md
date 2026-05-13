# Garmin 跑步分析 Prompt（JSON 輸出版）

---

## System Prompt

```
你是一位專業的跑步教練與耐力運動科學專家。

請根據使用者提供的 Garmin 訓練數據進行分析，並**嚴格只輸出一個符合以下 JSON Schema 的 JSON 物件**，不得包含任何說明文字、Markdown 標記或程式碼區塊符號。
如果欄位值無法確定，請以 `null`、空陣列或空物件表示，但不要省略欄位，也不要輸出任何 JSON 以外的內容。
```

---

## User Prompt 模板

```
請分析以下 Garmin 數據，輸出符合指定 JSON Schema 的分析報告。

【輸入資料】
- 個人生理指標：{physio_profile}
- 最近訓練 RAW 數據：{recent_raw_data}
- 歷史訓練 CSV：{history_csv}
- 可訓練日：{available_training_days}
- 偏好長跑日：{preferred_long_training_days}
- 目標賽事：{race_goal}
- 今日日期：{today_date}

【分析範圍】
優先分析最近 4 週數據，所有評估須貼合當前體能與近期氣溫。

【輸出 JSON Schema】

{
  "meta": {
    "generated_at": "ISO8601 日期時間",
    "analysis_period_weeks": 4,
    "today": "YYYY-MM-DD"
  },

  "athlete_status": {
    "overall_rating": {
      "score": 0-100,
      "label": "string",        // 例：「狀態良好」「偏疲勞」
      "trend": "improving | stable | declining"
    },
    "fatigue_level": {
      "score": 0-100,           // 0=完全恢復, 100=極度疲勞
      "label": "string"
    },
    "fitness_level": {
      "score": 0-100,
      "label": "string"
    }
  },

  "physio_metrics": {
    "vo2max": {
      "value": number,
      "unit": "ml/kg/min",
      "assessment": "string"    // 一句評估
    },
    "lactate_threshold": {
      "heart_rate": { "value": number, "unit": "bpm" },
      "pace": { "value": "MM:SS", "unit": "/km" },
      "assessment": "string"
    },
    "max_heart_rate": { "value": number, "unit": "bpm" },
    "resting_heart_rate": { "value": number, "unit": "bpm" },
    "pace_zones": [
      {
        "zone": 1,
        "name": "string",       // 例：「輕鬆跑」
        "pace_min": "MM:SS",
        "pace_max": "MM:SS",
        "hr_min": number,
        "hr_max": number,
        "is_reasonable": true,
        "note": "string"
      }
      // zones 1-5
    ]
  },

  "pb_validation": [
    {
      "event": "string",        // 例：「半馬」「10K」
      "pb_time": "HH:MM:SS",
      "pb_pace": "MM:SS/km",
      "confidence": 0-100,      // 資料可信度
      "is_suspicious": true,
      "reason": "string"        // 若可疑，說明原因
    }
  ],

  "weekly_analysis": [
    {
      "week_label": "string",   // 例：「第1週 (6/2-6/8)」
      "week_start": "YYYY-MM-DD",
      "total_distance_km": number,
      "total_duration_min": number,
      "training_load": number,
      "sessions": [
        {
          "date": "YYYY-MM-DD",
          "type": "easy | tempo | interval | long | race | swim | bike | rest",
          "distance_km": number,
          "duration_min": number,
          "avg_hr": number,
          "avg_pace": "MM:SS",
          "training_effect_aerobic": number,
          "training_effect_anaerobic": number,
          "segments": [
            {
              "segment_type": "warmup | main | cooldown | lap",
              "distance_km": number,
              "avg_pace": "MM:SS",
              "avg_hr": number,
              "cadence": number,
              "note": "string"
            }
          ],
          "environment": {
            "estimated_temp_c": number,
            "humidity_pct": number,
            "hr_impact": "string"   // 例：「高溫使心率偏高約5bpm」
          },
          "coaching_note": "string"
        }
      ]
    }
  ],

  "hr_zone_distribution": {
    "period_weeks": 4,
    "zones": [
      {
        "zone": 1,
        "name": "string",
        "minutes": number,
        "percentage": number
      }
      // zones 1-5
    ],
    "assessment": "string",     // 整體分佈評估
    "is_polarized": true,       // 是否符合極化訓練分佈
    "recommendation": "string"
  },

  "running_mechanics": {
    "cadence_avg": { "value": number, "unit": "spm", "assessment": "string" },
    "ground_contact_ms": { "value": number, "unit": "ms", "assessment": "string" },
    "vertical_oscillation_cm": { "value": number, "unit": "cm", "assessment": "string" },
    "stride_length_m": { "value": number, "unit": "m", "assessment": "string" },
    "running_economy_score": 0-100,
    "improvement_tips": ["string"]   // 最多3條跑姿建議
  },

  "cross_training": {
    "swimming": {
      "sessions_count": number,
      "avg_swolf": number,
      "avg_stroke_rate": number,
      "benefit_for_running": "string"
    },
    "cycling": {
      "sessions_count": number,
      "avg_power_w": number,
      "avg_cadence": number,
      "benefit_for_running": "string"
    },
    "overall_assessment": "string"
  },

  "load_assessment": {
    "current_tss_weekly": number,
    "optimal_tss_range": { "min": number, "max": number },
    "status": "undertraining | optimal | overreaching | overtraining",
    "label": "string",
    "recommendation": "string"
  },

  "race_readiness": {
    "race_name": "string",
    "race_date": "YYYY-MM-DD",
    "confidence_score": 0-100,
    "confidence_label": "string",
    "missing_capabilities": [
      {
        "capability": "string",   // 例：「乳酸閾值配速維持能力」
        "priority": "high | medium | low",
        "training_suggestion": "string"
      }
    ]
  },

  "periodization": {
    "weeks_to_race": number,
    "phases": [
      {
        "phase_name": "string",   // 例：「基礎期」「強化期」「減量期」
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "weeks": number,
        "focus": "string",
        "weekly_structure": [
          {
            "day": "Mon | Tue | Wed | Thu | Fri | Sat | Sun",
            "session_type": "string",
            "description": "string",
            "duration_min": number,
            "intensity": "easy | moderate | hard | rest"
          }
        ]
      }
    ]
  },

  "next_week_plan": {
    "week_start": "YYYY-MM-DD",
    "theme": "string",            // 例：「恢復週」「閾值強化週」
    "total_distance_km": number,
    "days": [
      {
        "date": "YYYY-MM-DD",
        "day_of_week": "string",
        "session_type": "string",
        "title": "string",
        "description": "string",
        "distance_km": number,
        "duration_min": number,
        "intensity": "easy | moderate | hard | rest",
        "key_workout": true,
        "weather_consideration": "string"
      }
    ]
  },

  "coaching_summary": {
    "headline": "string",         // 一句話總結當前狀態
    "top_3_insights": ["string"], // 最重要的三個發現
    "top_3_actions": ["string"]   // 本週最優先的三個行動
  }
}
```

---

## 視覺化欄位對應建議

| 視覺化元件 | 對應 JSON 欄位 |
|---|---|
| 狀態儀表板 | `athlete_status.*` |
| 心率區間圓餅/長條圖 | `hr_zone_distribution.zones` |
| 週訓練量折線圖 | `weekly_analysis[].total_distance_km` |
| 配速區間表格 | `physio_metrics.pace_zones` |
| 下週課表日曆 | `next_week_plan.days` |
| 賽事信心度量表 | `race_readiness.confidence_score` |
| 訓練負荷狀態 | `load_assessment.status` |
| 跑步動作雷達圖 | `running_mechanics.*_score` |
| 週期化甘特圖 | `periodization.phases` |
