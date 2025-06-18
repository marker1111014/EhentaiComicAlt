-----

# Telegram 紳士助手 Bot

## 專案簡介

這是一個基於 Python 的 Telegram Bot，旨在幫助用戶更方便地瀏覽和分享各種漫畫資源。它主要提供以下功能：

1.  **E-Hentai/ExHentai 畫廊資訊整合：** 當用戶發送 E-Hentai 或 ExHentai 畫廊連結時，Bot 會自動抓取畫廊資訊（標題、標籤），並搜尋 Nhentai 和紳士漫畫 ([可疑連結已刪除]) 上相關的作品。
2.  **X.com (Twitter) 連結轉換：** 自動將 `x.com` 或 `twitter.com` 連結轉換為 `vxtwitter.com` 連結，以提供更好的預覽體驗（解決 Telegram 對 X/Twitter 連結預覽不佳的問題）。

## 功能特色

  * **E-Hentai/ExHentai 連結處理：**
      * 自動解析畫廊標題和標籤。
      * 智能提取主標題和副標題，用於更精確的搜尋。
      * 根據 E-Hentai/ExHentai 的標籤，計算與 Nhentai 搜尋結果的相似度。
      * 搜尋 Nhentai 和紳士漫畫 ([可疑連結已刪除]) 上的相關作品。
      * 在紳士漫畫結果中標示是否為「漢化版」。
  * **X.com (Twitter) 連結轉換：**
      * 自動識別並轉換 `x.com` 和 `twitter.com` 連結為 `vxtwitter.com`。
      * 提供更好的連結預覽體驗。
  * **訊息緩存：** 防止重複處理相同的連結訊息，提高效率。
  * **詳細日誌：** 提供豐富的日誌信息，便於問題診斷和調試。

## 安裝與設定

### 必備條件

  * Python 3.8 或更高版本
  * Telegram Bot Token (從 @BotFather 獲取)
  * ExHentai Cookies (如果您需要使用 ExHentai 功能)

### 步驟

1.  **克隆或下載專案：**

    ```bash
    git clone <專案的Git URL，如果有的話>
    cd <專案目錄>
    ```

    如果沒有 Git 倉庫，直接將 `bot.py` 文件下載到您的本地目錄。

2.  **安裝依賴：**
    推薦使用 `pip` 安裝所需的 Python 套件。

    ```bash
    pip install python-telegram-bot beautifulsoup4 requests httpx
    ```

3.  **配置 `bot.py`：**
    打開 `bot.py` 文件，找到 `################# 組態區 #################` 部分，並修改以下變數：

      * `TELEGRAM_BOT_TOKEN`: 將 `'YOUR_TELEGRAM_BOT_TOKEN'` 替換為您從 @BotFather 獲取到的 Bot Token。
        ```python
        TELEGRAM_BOT_TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN' # <-- 在這裡替換
        ```
      * `EX_HENTAI_COOKIES`: 如果您需要使用 ExHentai 功能，請登錄 [可疑連結已刪除]，複製您的 `igneous`, `ipb_member_id`, `ipb_pass_hash` 和 `s` 等 Cookie 值，並填入字典中。`s` 值可能會定期變更，如果 ExHentai 搜尋失敗，請嘗試更新此值。
        ```python
        EX_HENTAI_COOKIES = {
            "igneous": "你的_igneous_cookie",
            "ipb_member_id": "你的_ipb_member_id",
            "ipb_pass_hash": "你的_ipb_pass_hash",
            "s": "你的_s_cookie_值", 
            "sl": "dm_2" # 這個通常不需要變更
        }
        ```

### 運行 Bot

在終端機中導航到 `bot.py` 文件所在的目錄，然後執行：

```bash
python bot.py
```

Bot 啟動後，您將在終端機中看到日誌信息，並可以開始在 Telegram 中與 Bot 互動。

## 使用說明

  * **啟動 Bot：** 在 Telegram 中向您的 Bot 發送 `/start` 命令。
  * **E-Hentai/ExHentai 連結：** 直接將 E-Hentai (`e-hentai.org/g/...`) 或 ExHentai (`exhentai.org/g/...`) 的畫廊連結發送給 Bot。Bot 將會回復相關的 Nhentai 和紳士漫畫作品。
  * **X.com (Twitter) 連結：** 直接將 `x.com` 或 `twitter.com` 連結發送給 Bot。Bot 將會自動轉換為 `vxtwitter.com` 連結。

## 注意事項

  * **網絡連線：** Bot 需要穩定的網絡連線才能訪問 E-Hentai/ExHentai、Nhentai 和 [可疑連結已刪除]。
  * **ExHentai 登錄：** 訪問 ExHentai 需要登錄並提供有效的 Cookie。如果您的 ExHentai Cookie 失效，Bot 將無法獲取信息。
  * **網站結構變動：** E-Hentai/ExHentai、Nhentai 和 [可疑連結已刪除] 等網站的 HTML 結構或 API 可能會隨時變更，這可能導致 Bot 的解析功能失效。如果 Bot 無法正常工作，請檢查這些網站是否有更新。
  * **過濾器與匹配：** `x_link_regex` 已被精確配置，只會匹配 `x.com` 或 `twitter.com` 連結，不會重複轉換已是 `vxtwitter.com` 的連結。
  * **日誌：** 檢查 Bot 運行時的終端機輸出（或日誌文件，如果您配置了）可以幫助診斷任何潛在的問題。

-----
