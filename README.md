# AI 跑步教練

這是一個 AI 驅動的跑步教練系統，可以從 Garmin 取得訓練數據，使用人工智慧分析並提供個人化的訓練建議。

## 功能特色

- 自動從 Garmin Connect 獲取跑步活動數據
- AI 分析訓練趨勢和表現
- 生成個人化訓練建議
- 輸出結構化分析報告

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
  - `ingestion/`: 數據獲取
  - `preprocessing/`: 數據預處理
  - `agents/`: AI 代理
  - `pipeline/`: 管道控制
- `prompts/`: AI 提示詞
- `output/`: 輸出文件

## 技術棧

- Python 3.13+
- Garmin Connect API
- Google Gemini AI
- Pandas

## 注意事項

- 確保 Garmin 帳號有數據
- API 可能有速率限制
- 首次運行可能需要手動驗證
