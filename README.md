# AI 跑步教練

這是一個 AI 驅動的跑步教練系統，可以從 Garmin 取得訓練數據，使用人工智慧分析並提供個人化的訓練建議。

## 功能特色

### 數據獲取
- 自動從 Garmin Connect 獲取跑步、游泳、自行車活動數據
- 完整的 Raw Data 支持，包括：

#### 跑步 (Running)
- **步頻 (Cadence)**: 判斷是「力量型」還是「頻率型」跑者（目標 180spm）
- **垂直振幅 (Vertical Oscillation)**: 評估跑步效率，避免體力浪費在向上跳
- **觸地時間 (Ground Contact Time)**: 判斷推蹬力量與受傷風險
- **安靜心率 (Resting HR)**: 計算「儲備心率 (HRR)」，比單看心率區間更準確
- **坡度 (Elevation)**: 高度增益/下降，不同坡度耗力完全不同
- **氣溫 (Temperature)**: 冬天夏天配速相同但耗力差異大
- **心率區間時間分布 (HR Time in Zone)**: Zone 1-5 各區間的訓練時間，了解訓練強度分布
- **功率區間時間分布 (Power Time in Zone)**: Zone 1-5 各區間的功率輸出時間分布（需支持功率計）
- **各距離 PB**: 1k, 2k, 5k, 10k, 半馬, 全馬
- **分段數據**: 每圈/每段的詳細配速、心率、步頻

#### 游泳 (Swimming)
- **划手數 (Stroke Count)** 及 **SWOLF**: 衡量游泳效率的關鍵指標
- **泳池長度與泳姿**: 記錄訓練環境與技術類型
- **心率區間時間分布 (HR Time in Zone)**: Zone 1-5 各區間的訓練時間
- **功率區間時間分布 (Power Time in Zone)**: Zone 1-5 各區間的功率輸出時間分布
- **各距離 PB**: 50m, 100m, 200m 等
- **分段數據**: 每段的效率指標

#### 自行車 (Cycling)
- **高度增益 (Elevation Gain)**: 區分平路 vs 爬坡
- **功率數據 (Power)**: 平均和最大功率輸出
- **踏頻 (Cadence)**: 騎行效率指標
- **心率區間時間分布 (HR Time in Zone)**: Zone 1-5 各區間的訓練時間
- **功率區間時間分布 (Power Time in Zone)**: Zone 1-5 各區間的功率輸出時間分布
- **各距離 PB**
- **分段數據**

### 數據分析
- AI 分析訓練趨勢和表現
- 自動分類跑者類型（力量型 vs 頻率型）
- 評估跑步效率指標
- 計算儲備心率與心率區間
- 生成個人化訓練建議

### 輸出報告
- 輸出結構化分析報告 CSV
- 包含所有 Raw Data 和計算後的指標

## 安裝與使用

1. 安裝依賴：
   ```bash
   pip install -r requirements.txt
   ```

2. 配置環境變數（.env 文件已包含）：
   - GARMIN_ACCOUNT: Garmin 帳號
   - GARMIN_PASSWORD: Garmin 密碼
   - GEMINI_KEY: Google Gemini API 金鑰

3. 運行管道：
   ```bash
   python run_pipeline.py
   ```

4. 查看輸出：`output/ai_analysis_YYYYMMDD.csv`

## 專案結構

- `src/`: 源代碼
  - `ingestion/garmin_client.py`: Garmin API 集成，獲取完整的 raw data
  - `preprocessing/data_processor.py`: 數據預處理、指標計算與分類
  - `agents/coach.py`: AI 教練代理
  - `pipeline/runner.py`: 管道控制
- `prompts/`: AI 提示詞
- `output/`: 輸出文件

## 數據流水線

```
Garmin API
    ↓
garmin_client.py (獲取原始活動數據 + 詳細指標)
    ↓
data_processor.py (清理、計算、分類、分析)
    ↓
coach.py (AI 分析與建議)
    ↓
output CSV (最終報告)
```

## 技術棧

- Python 3.13+
- Garmin Connect API (garminconnect library)
- Google Gemini AI
- Pandas

## 注意事項

- 確保 Garmin 帳號有數據
- API 可能有速率限制
- 首次運行可能需要手動驗證
- 某些高級指標（如功率數據）需要相應的 Garmin 設備支持
- **心率和功率區間數據需要兼容的 Garmin 設備支持，舊活動可能缺少此數據**
