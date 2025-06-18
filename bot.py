import logging
import os
import requests
import uuid
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
import urllib.parse
import random
import re
import json
import time
import traceback

# --- 緩存已處理的訊息連結，用於處理重複訊息 ---
# 格式: {(chat_id, message_id): "processed_link_string"}
# 儲存每個訊息處理過的連結，以便判斷是否已處理過相同的訊息
PROCESSED_LINKS_CACHE = {} 

################# 組態區 #################
# IMPORTANT: 請替換為您自己的 Telegram Bot Token
# 如果有兩個 Bot Token，可以選擇一個作為主 Bot，或者使用環境變數
TELEGRAM_BOT_TOKEN = 'Token' 

# --- E-Hentai 相關設定 ---
E_HEN_TAI_BASE_URL = "https://e-hentai.org/"

# --- ExHentai 相關設定 ---
EX_HEN_TAI_BASE_URL = "https://exhentai.org/"
# IMPORTANT: 請替換成你的 ExHentai Cookies
EX_HENTAI_COOKIES = {
    "igneous": "COOKIES",
    "ipb_member_id": "COOKIES",
    "ipb_pass_hash": "COOKIES",
    "s": "COOKIES", # s 值通常會變，建議定期更新
    "sl": "COOKIES"
}

# --- Nhentai 相關設定 ---
NHENTAI_BASE_URL = "https://nhentai.net/"

# --- 紳士漫畫 (wnacg.com) 相關設定 ---
WNACG_BASE_URL = "https://www.wnacg.com/"


# 設定日誌記錄
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 將正規表達式定義為全域變量，以便在處理函數中重複使用
e_ex_hentai_regex = re.compile(
    r'https?://(?:e-hentai|exhentai)\.org/g/\d+/[0-9a-fA-F]+/?', re.IGNORECASE
)
# Adjusted to only match x.com or twitter.com, not vxtwitter.com
# 這個正則表達式在匹配時沒有問題，它不會匹配 vxtwitter.com
x_link_regex = re.compile(
    r'https?://(?:x|twitter)\.com/\S+', re.IGNORECASE
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /start 命令。"""
    await update.message.reply_text('你好！請發送 E-Hentai/ExHentai 連結，我會為您尋找相關的 Nhentai 和紳士漫畫作品。您也可以發送 X.com (Twitter) 連結，我會將其轉換為 VxTwitter 連結。')

def clean_tag(tag: str) -> str:
    """清理標籤字串，移除常見的前綴和不必要的空格。"""
    tag = tag.lower().strip()
    # 移除 E-Hentai/ExHentai 中常見的標籤類型前綴
    prefixes = ['artist:', 'group:', 'language:', 'parody:', 'character:', 'tag:']
    for prefix in prefixes:
        if tag.startswith(prefix):
            tag = tag[len(prefix):].strip()
    return tag

def clean_title_string(title_str: str) -> str:
    """清理標題字串，移除所有方括號 [] 及其內部內容，
    以及其他常見的標籤和不必要的空格。
    此函數主要用於獲取乾淨的「主標題」和「副標題」。
    """
    cleaned = title_str
    # 移除所有方括號及其內部內容
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    
    # 移除圓括號內的常見標籤 (如語言、版本等，非系列名稱)
    # 這裡需要更精確，避免移除真正的系列名
    keywords_to_remove_from_paren = [
        r'\((?:Chinese|English|Japanese|漢化|中國翻訳|日語|英訳|無修正|DL版|Digital|MTL|machine translation)\)',
        r'\(C\d+\)', # Comiket標識
        r'\(vol\.?\s*\d+\)', # 卷/章節標識
        r'\(v\.?\s*\d+\)' # 版本號
    ]
    for kw_regex in keywords_to_remove_from_paren:
        cleaned = re.sub(kw_regex, '', cleaned, flags=re.IGNORECASE).strip()

    # 移除可能剩下的多餘空格或連字元
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip() # 多個空格變為一個
    cleaned = re.sub(r'^\s*-\s*', '', cleaned).strip() # 開頭的連字元
    cleaned = re.sub(r'\s*-\s*$', '', cleaned).strip() # 結尾的連字元
    return cleaned

def clean_title_for_nhentai_search(title_str: str) -> str:
    """
    為 Nhentai 搜尋特別設計的標題清理函數。
    比 `clean_title_string` 更溫和，會保留方括號和大部分圓括號內容，
    只移除最可能幹擾 N 站搜尋的特定標識。
    """
    cleaned = title_str
    # 移除圓括號內的語言、翻譯標識、卷號、版本號等，但保留其他括號內容
    keywords_to_remove_from_paren_nhentai = [
        r'\((?:Chinese|English|Japanese|漢化|中國翻訳|日語|英訳|無修正|DL版|Digital|MTL|machine translation|color|彩色)\)',
        r'\(C\d+\)', # Comiket標識
        r'\(vol\.?\s*\d+\)', # 卷/章節標識
        r'\(v\.?\s*\d+\)' # 版本號
    ]
    for kw_regex in keywords_to_remove_from_paren_nhentai:
        cleaned = re.sub(kw_regex, '', cleaned, flags=re.IGNORECASE).strip()

    # 移除多餘空格
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    
    # 移除開頭或結尾的連字元
    cleaned = re.sub(r'^\s*-\s*', '', cleaned).strip() 
    cleaned = re.sub(r'\s*-\s*$', '', cleaned).strip()

    return cleaned


def calculate_similarity(e_ex_hentai_tags: dict, nhentai_tags: dict) -> float:
    """
    計算 E-Hentai/ExHentai 標籤與 Nhentai 標籤的相似度。
    標籤類型會影響權重，完全匹配的標籤權重更高。
    """
    if not e_ex_hentai_tags or not nhentai_tags:
        return 0.0

    total_possible_score = 0
    actual_score = 0

    # 定義標籤類型權重
    tag_weights = {
        'artist': 5,
        'group': 4,
        'parody': 3,
        'character': 3,
        'language': 2,
        'tag': 1
    }

    # 處理 E-Hentai/ExHentai 標籤
    e_ex_hentai_processed_tags = {}
    for tag_type, tags in e_ex_hentai_tags.items():
        cleaned_tags = [clean_tag(tag) for tag in tags]
        e_ex_hentai_processed_tags[tag_type] = cleaned_tags
        total_possible_score += len(cleaned_tags) * tag_weights.get(tag_type, 1)

    # 處理 Nhentai 標籤
    nhentai_processed_tags = {}
    for tag_obj in nhentai_tags:
        tag_type = tag_obj.get('type')
        tag_name = clean_tag(tag_obj.get('name'))
        if tag_type and tag_name:
            nhentai_processed_tags.setdefault(tag_type, []).append(tag_name)
        
    # 計算分數
    for e_type, e_tags in e_ex_hentai_processed_tags.items():
        weight = tag_weights.get(e_type, 1)
        if e_type in nhentai_processed_tags:
            for e_tag in e_tags:
                if e_tag in nhentai_processed_tags[e_type]:
                    actual_score += weight # 同類型標籤匹配
                # else:
                #     # 考慮跨類型但文字匹配的標籤 (例如 E-Hentai 的 character 在 Nhentai 是 tag)
                #     # 這部分比較複雜且可能引入雜訊，暫不實作
    
    if total_possible_score == 0:
        return 0.0
        
    return (actual_score / total_possible_score) * 100

def get_e_ex_hentai_info(gallery_url: str) -> tuple[str, dict, str, str, str]:
    """
    從 E-Hentai/ExHentai 連結抓取畫廊標題和標籤。
    嘗試解析並返回主標題、副標題，以及額外的日文標題（如果存在且不同）。
    返回: (總體標題, 標籤字典, 主標題, 副標題, 額外日文主標題)
    """
    cookies_to_use = EX_HENTAI_COOKIES if "exhentai" in gallery_url else {}
    
    try:
        response = requests.get(gallery_url, cookies=cookies_to_use, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 獲取英文標題 (gn)
        english_title_element = soup.find(id='gn')
        full_english_title = english_title_element.get_text(strip=True) if english_title_element else ""

        # 獲取日文標題 (gj)
        japanese_title_element = soup.find(id='gj')
        full_japanese_title = japanese_title_element.get_text(strip=True) if japanese_title_element else ""
        
        # 預設總體標題為英文標題，如果英文標題不存在則使用日文標題
        full_gallery_title = full_english_title if full_english_title else full_japanese_title
        if not full_gallery_title:
            full_gallery_title = "未知標題"

        # --- 解析主標題和副標題 ---
        main_title_parsed = ""
        subtitle_parsed = ""
        extra_japanese_main_title = "" # 用於儲存清理後的日文主標題

        # 優先處理英文標題來確定 main_title_parsed 和 subtitle_parsed
        current_processing_title = full_english_title if full_english_title else full_gallery_title

        # 1. 嘗試以 '-' 分割主副標題 (在清理方括號之後進行)
        cleaned_current_processing_title = clean_title_string(current_processing_title)
        
        if ' - ' in cleaned_current_processing_title:
            parts = [p.strip() for p in cleaned_current_processing_title.split(' - ', 1)]
            if len(parts) == 2:
                main_title_parsed = parts[0]
                subtitle_parsed = parts[1]
        
        # 如果沒有從 '-' 分割出副標題，或副標題不夠好，則嘗試從圓括號中提取
        # 注意：此處的圓括號內內容，如果不是常見的標籤（如語言、版本），則視為副標題
        if not subtitle_parsed or len(subtitle_parsed) < 3: # 再次嘗試，或覆蓋短的副標題
            temp_title_for_paren_check = cleaned_current_processing_title # 在此基礎上檢查圓括號
            match_series = re.search(r'\(([^)]+)\)$', temp_title_for_paren_check)
            if match_series:
                potential_subtitle_from_paren = match_series.group(1).strip()
                # 判斷是否為有效副標題（不是單純的數字年份、卷號、版本號或語言）
                if len(potential_subtitle_from_paren) > 2 and \
                   not re.fullmatch(r'\d{4}', potential_subtitle_from_paren) and \
                   not re.fullmatch(r'(?:vol|ch|chapter)\.?\s*\d+', potential_subtitle_from_paren, flags=re.IGNORECASE) and \
                   not re.fullmatch(r'v\.?\s*\d+', potential_subtitle_from_paren, flags=re.IGNORECASE) and \
                   potential_subtitle_from_paren.lower() not in ['chinese', 'english', 'japanese', 'digital', '漢化', 'dl版', '無修正', 'korean', 'thai', 'vietnamese']:
                    
                    subtitle_parsed = potential_subtitle_from_paren
                    main_title_parsed = temp_title_for_paren_check[:match_series.start()].strip()
                else:
                    main_title_parsed = temp_title_for_paren_check # 使用清理過但未移除括號的主標題

        # 如果主標題仍然是空或沒有從上述方法中獲得，則使用原始英文標題作為基礎
        if not main_title_parsed:
            main_title_parsed = clean_title_string(full_english_title or full_japanese_title or full_gallery_title)
            subtitle_parsed = "" # 清空副標題，因為可能錯誤拆分

        # 如果副標題和主標題相同或極其相似，則清空副標題
        if subtitle_parsed and (main_title_parsed.lower() == subtitle_parsed.lower() or 
                                main_title_parsed.lower().startswith(subtitle_parsed.lower())):
            subtitle_parsed = ""
        
        # 如果 extra_japanese_main_title 和 main_title_parsed 相同（可能是因為只有英文標題或兩者完全一樣）
        # 這裡應該處理日文標題的清理，並在不與英文標題重複時使用
        if full_japanese_title and full_japanese_title != full_english_title:
             cleaned_japanese_title = clean_title_string(full_japanese_title)
             if cleaned_japanese_title and cleaned_japanese_title != main_title_parsed:
                 extra_japanese_main_title = cleaned_japanese_title

        tags = {}
        taglist_div = soup.find(id='taglist')
        if taglist_div:
            for row in taglist_div.find_all('tr'):
                tc_td = row.find('td', class_='tc')
                if tc_td:
                    raw_type = tc_td.text.replace(':', '').strip().lower()
                    type_mapping = {
                        'artist': 'artist', 'group': 'group', 'parody': 'parody', 
                        'character': 'character', 'language': 'language', 'female': 'tag', 
                        'male': 'tag', 'fetish': 'tag', 'misc': 'tag', 'reclass': 'tag', 'other': 'tag' # 加入 'other'
                    }
                    mapped_type = type_mapping.get(raw_type, 'tag')
                    
                    gt_divs = row.find_all('div', class_=re.compile(r'gt[a-z]'))
                    for div_tag in gt_divs:
                        a_tag = div_tag.find('a')
                        if a_tag:
                            tag_name = a_tag.text.strip()
                            if tag_name:
                                tags.setdefault(mapped_type, []).append(tag_name)

        logger.info(f"E/ExHentai 標題解析結果: 總標題='{full_gallery_title}', 主標題='{main_title_parsed}', 副標題='{subtitle_parsed}', 額外日文主標題='{extra_japanese_main_title}'")
        return full_gallery_title, tags, main_title_parsed, subtitle_parsed, extra_japanese_main_title

    except requests.exceptions.RequestException as e:
        logger.error(f"從 {gallery_url} 獲取資訊失敗: {e}")
        return "獲取失敗", {}, "", "", ""
    except Exception as e:
        logger.error(f"解析 {gallery_url} 頁面時發生錯誤: {e}\n{traceback.format_exc()}")
        return "解析錯誤", {}, "", "", ""

def search_nhentai(full_query: str, main_title: str, subtitle: str, extra_japanese_main_title: str, original_tags: dict) -> list:
    """
    在 Nhentai 上搜尋相關作品，並計算相似度。
    會嘗試多種查詢方式以提高命中率。
    """
    search_results = []
    
    queries_to_try = []

    # 1. 優先加入原始的 E-Hentai/ExHentai 完整標題 (full_query)
    # Nhentai 搜尋可能能處理方括號等特殊字元
    if full_query:
        queries_to_try.append(full_query)

    # 2. 加入為 Nhentai 搜尋專門清理過的標題
    nhentai_cleaned_main_title = clean_title_for_nhentai_search(main_title)
    if nhentai_cleaned_main_title and nhentai_cleaned_main_title not in queries_to_try:
        queries_to_try.append(nhentai_cleaned_main_title)
    
    # 3. 加入為 Nhentai 搜尋專門清理過的日文標題 (如果存在且不同)
    if extra_japanese_main_title:
        nhentai_cleaned_japanese_title = clean_title_for_nhentai_search(extra_japanese_main_title)
        if nhentai_cleaned_japanese_title and nhentai_cleaned_japanese_title not in queries_to_try and nhentai_cleaned_japanese_title != nhentai_cleaned_main_title:
            queries_to_try.append(nhentai_cleaned_japanese_title)

    # 4. 從原始標籤中提取作者和組別作為額外查詢關鍵字
    artists = original_tags.get('artist', [])
    groups = original_tags.get('group', [])
    
    # 組合查詢詞："作者" + 清理後的標題，或單獨的"作者"
    for artist in artists:
        if nhentai_cleaned_main_title:
            queries_to_try.append(f'"{artist}" {nhentai_cleaned_main_title}')
        queries_to_try.append(f'"{artist}"') 
    for group in groups:
        if nhentai_cleaned_main_title:
            queries_to_try.append(f'"{group}" {nhentai_cleaned_main_title}')
        queries_to_try.append(f'"{group}"')

    # 去重
    queries_to_try = list(dict.fromkeys(queries_to_try))
    queries_to_try = [q for q in queries_to_try if q] # 確保查詢詞非空
    logger.info(f"Nhentai 搜尋嘗試的查詢詞: {queries_to_try}")

    for q in queries_to_try:
        if not q: continue
        search_url = f"{NHENTAI_BASE_URL}api/galleries/search?query={urllib.parse.quote(q)}"
        logger.info(f"Nhentai 搜尋 URL: {search_url}")
        try:
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data and data.get('result'):
                for entry in data['result']:
                    nhentai_id = entry['id']
                    # 優先使用 pretty 標題，其次是英文標題
                    nhentai_title_obj = entry['title'].get('pretty') or entry['title'].get('english')
                    nhentai_tags = entry['tags']
                    nhentai_url = f"{NHENTAI_BASE_URL}g/{nhentai_id}/"

                    similarity_score = calculate_similarity(original_tags, nhentai_tags)
                    search_results.append({
                        'title': nhentai_title_obj,
                        'url': nhentai_url,
                        'similarity': similarity_score
                    })
                # 如果找到任何結果，就停止更多嘗試，避免重複和不相關結果
                if search_results:
                    break 

        except requests.exceptions.RequestException as e:
            logger.warning(f"Nhentai 搜尋 '{q}' 失敗: {e}")
        except json.JSONDecodeError:
            logger.warning(f"Nhentai 搜尋 '{q}' 返回非 JSON 響應。")
        except Exception as e:
            logger.error(f"Nhentai 搜尋 '{q}' 時發生錯誤: {e}\n{traceback.format_exc()}")

    # 按相似度降序排序
    search_results = sorted(search_results, key=lambda x: x['similarity'], reverse=True)
    return search_results[:5] # 返回前5個最相關的結果

def get_wnacg_info(gallery_url: str) -> dict:
    """
    從紳士漫畫畫廊頁面獲取額外資訊，例如是否為漢化版。
    """
    try:
        response = requests.get(gallery_url, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        is_translated = False

        # --- 最可靠的判斷方式1：明確的分類標籤 (e.g., 分類：同人誌／漢化) ---
        category_label = soup.find('label', string=re.compile(r'分類：.*?漢化'))
        if category_label:
            is_translated = True
            logger.info(f"Found '漢化' in explicit category label for {gallery_url}")
            return {"is_translated": is_translated} 
        
        # --- 最可靠的判斷方式2：麵包屑導航中的漢化分類連結 ---
        # 檢查連結是否指向紳士漫畫的特定漢化分類 ID
        # 紳士漫畫漢化分類的 href 包含 'cate-1.html' (同人誌), 'cate-9.html' (單行本), 'cate-10.html' (雜誌&短篇), 'cate-20.html' (韓漫)
        breadcrumb_div = soup.find('div', class_='png bread')
        if breadcrumb_div:
            for a_tag in breadcrumb_div.find_all('a'):
                href = a_tag.get('href')
                if href and ('cate-1.html' in href or 'cate-9.html' in href or 'cate-10.html' in href or 'cate-20.html' in href) \
                   and '漢化' in a_tag.text: # 確保連結文字也包含'漢化'
                    is_translated = True
                    logger.info(f"Found '漢化' category link in breadcrumb for {gallery_url}")
                    return {"is_translated": is_translated}

        # --- 輔助判斷方式：h2 標題中是否包含「漢化組」或「chinese translated」 ---
        # 這個元素是針對特定漫畫的標題，可能包含漢化組名
        title_element_h2 = soup.find('h2') # 找到 h2 標籤，不限 class
        if title_element_h2 and ('漢化組' in title_element_h2.text or 'chinese translated' in title_element_h2.text.lower()):
            is_translated = True
            logger.info(f"Found '漢化組' in h2 title for {gallery_url}")
            return {"is_translated": is_translated} # 如果標題明確，直接返回

        # --- 輔助判斷方式：標籤中是否包含 '漢化' 或 'chinese' ---
        # 這是較弱的檢查，因為標籤可能不夠精確
        tag_container = soup.find('div', class_='addtags') 
        if tag_container:
            for a_tag in tag_container.find_all('a', class_='tagshow'): # 只檢查 class 為 'tagshow' 的標籤
                tag_name = a_tag.text.strip().lower()
                if '漢化' in tag_name or 'chinese' in tag_name:
                    is_translated = True
                    logger.info(f"Found '漢化' in tag for {gallery_url}")
                    break # 找到一個就夠了

        # 注意：已移除對 <title> 標籤和 <meta name="description"> 的檢查，
        # 因為它們包含網站通用資訊，容易導致誤判。

        return {"is_translated": is_translated}

    except requests.exceptions.RequestException as e:
        logger.warning(f"從紳士漫畫 {gallery_url} 獲取詳細資訊失敗: {e}")
        return {"is_translated": False}
    except Exception as e:
        logger.error(f"解析紳士漫畫 {gallery_url} 頁面時發生錯誤: {e}\n{traceback.format_exc()}")
        return {"is_translated": False}


def search_wnacg_by_title(full_query: str, main_title: str = "", subtitle: str = "", extra_japanese_main_title: str = "") -> list:
    """
    在紳士漫畫 (wnacg.com) 上根據標題搜尋作品。
    接收主標題和副標題，以及額外的日文主標題，並將它們加入到搜尋查詢詞的列表中。
    每個結果會額外判斷是否為漢化版。
    """
    search_results = []
    
    queries_to_try = []

    # 1. 優先加入原始的完整標題 (full_query)，因為 WNACG 的搜尋可能處理這些方括號
    if full_query:
        queries_to_try.append(full_query)

    # 2. 加入解析出的主標題 (已經過徹底清理，不含方括號) - 作為後備或輔助
    if main_title and main_title not in queries_to_try:
        queries_to_try.append(main_title)

    # 3. 加入解析出的副標題 (已經過徹底清理，不含方括號) - 作為後備或輔助
    if subtitle and subtitle not in queries_to_try:
        queries_to_try.append(subtitle)
    
    # 4. 加入額外日文主標題 (已經過徹底清理，不含方括號) - 作為後備或輔助
    if extra_japanese_main_title and extra_japanese_main_title not in queries_to_try:
        queries_to_try.append(extra_japanese_main_title)

    # 5. 生成更精簡的標題變體 (從最乾淨的主標題開始)
    # 如果主標題包含數字序列 (例如 "Title 2" 中的 "2")，嘗試移除數字以搜尋系列第一部
    if main_title and re.search(r'\s+\d+$', main_title): # 匹配以數字結尾的標題
        query_without_number = re.sub(r'\s+\d+$', '', main_title).strip()
        if query_without_number and query_without_number not in queries_to_try:
            queries_to_try.append(query_without_number)

    # 嘗試用 ' - ' 分割清理後的核心標題，取主要部分 (如果之前沒有以此分隔)
    # 這裡的 main_title 已經是清理後的了
    if ' - ' in main_title and main_title not in queries_to_try:
        parts = [p.strip() for p in main_title.split(' - ') if p.strip()]
        if len(parts) > 1:
            for p in parts: # 遍歷所有分割部分，作為獨立查詢
                 if p and p not in queries_to_try: # 避免重複
                     queries_to_try.append(p)
    
    # 如果標題仍很長，嘗試只取前面一部分詞
    if main_title and len(main_title.split()) > 5:
        short_query = ' '.join(main_title.split()[:5]).strip()
        if short_query and short_query not in queries_to_try:
            queries_to_try.append(short_query)
    
    # 去除重複並確保非空
    queries_to_try = [q for q in list(dict.fromkeys(queries_to_try)) if q]
    
    logger.info(f"紳士漫畫搜尋嘗試的查詢詞 (包括主副標題衍生): {queries_to_try}")

    for q in queries_to_try:
        if not q: continue
        search_url = f"{WNACG_BASE_URL}search/?q={urllib.parse.quote(q)}"
        logger.info(f"紳士漫畫搜尋 URL: {search_url}")
        
        try:
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            galleries = soup.select('li.gallary_item') 
            
            for gallery in galleries:
                title_tag = gallery.select_one('div.info div.title a')
                if title_tag:
                    # 使用 BeautifulSoup 解析 HTML 並獲取純文字，這會自動處理 <em> 標籤
                    # 注意: 這裡的 title 是顯示用的，搜尋匹配應基於 query
                    clean_title_soup = BeautifulSoup(str(title_tag), 'html.parser')
                    title = clean_title_soup.get_text(strip=True)

                    relative_url = title_tag.get('href')
                    if relative_url:
                        full_url = urllib.parse.urljoin(WNACG_BASE_URL, relative_url)
                        
                        # 在這裡呼叫 get_wnacg_info 函數來獲取漢化狀態
                        wnacg_info = get_wnacg_info(full_url)
                        is_translated = wnacg_info.get("is_translated", False)

                        search_results.append({
                            'title': title, 
                            'url': full_url,
                            'similarity': 0, # 紳士漫畫不計算相似度，設為0
                            'is_translated': is_translated # 新增漢化標誌
                        })
            if search_results: 
                break # 如果找到任何結果，就停止更多嘗試，避免不相關結果

        except requests.exceptions.RequestException as e:
            logger.warning(f"紳士漫畫搜尋 '{q}' 失敗: {e}")
        except Exception as e:
            logger.error(f"解析紳士漫畫搜尋結果 '{q}' 時發生錯誤: {e}\n{traceback.format_exc()}")
            
    unique_results = {}
    for res in search_results:
        unique_results[res['url']] = res
    
    return list(unique_results.values())[:5]


async def handle_e_ex_hentai_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 E-Hentai 或 ExHentai 連結，並搜尋相關的 Nhentai 和紳士漫畫作品。"""
    message = update.message 
    if not message or not message.text:
        return

    chat_id = message.chat.id
    message_id = message.message_id
    
    # 使用全域定義的 e_ex_hentai_regex 來提取訊息中的實際連結
    match = e_ex_hentai_regex.search(message.text)
    if not match:
        # 理論上這個分支不應該被觸發，因為 MessageHandler 的 filter 已經匹配了
        logger.warning(f"處理器觸發但未在訊息中找到 E-Hentai 連結: {message.text}")
        return 
    
    link = match.group(0) # 提取匹配到的完整連結字串
    
    # 檢查這個訊息的當前連結內容是否和緩存中已處理的內容相同
    if PROCESSED_LINKS_CACHE.get((chat_id, message_id)) == link:
        logger.info(f"訊息 {message_id} 已處理過連結 {link}，跳過重新處理。")
        return

    processing_message = await context.bot.send_message(
        chat_id=chat_id,
        text="正在分析連結並搜尋相關作品，請稍候...",
        reply_to_message_id=message_id 
    )

    try:
        # Step 1: 從 E-Hentai/ExHentai 連結獲取畫廊資訊
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text="[🟩⬜⬜] 正在從 E-Hentai/ExHentai 獲取畫廊資訊..."
        )
        # full_gallery_title 是原始的、未經 clean_title_string 處理的標題
        e_ex_hentai_title, e_ex_hentai_tags, main_title_parsed, subtitle_parsed, extra_japanese_main_title = get_e_ex_hentai_info(link)

        if e_ex_hentai_title == "獲取失敗" or not e_ex_hentai_title:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=processing_message.message_id,
                text="❌ 無法從 E-Hentai/ExHentai 連結獲取畫廊資訊，請檢查連結是否有效或權限是否足夠。"
            )
            PROCESSED_LINKS_CACHE[(chat_id, message_id)] = link
            return

        # Step 2: 搜尋 Nhentai 
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text=f"[🟩🟩⬜] 正在 Nhentai 搜尋 `{e_ex_hentai_title}` 相關作品...",
            parse_mode='Markdown'
        )
        # 將所有相關標題傳入 Nhentai 搜尋函數
        nhentai_results = search_nhentai(e_ex_hentai_title, main_title_parsed, subtitle_parsed, extra_japanese_main_title, e_ex_hentai_tags)

        # Step 3: 搜尋紳士漫畫 (wnacg.com)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text=f"[🟩🟩🟩] 正在紳士漫畫搜尋 `{e_ex_hentai_title}` 相關作品...", # 這裡顯示原始標題，因為會優先使用它來搜尋
            parse_mode='Markdown'
        )
        wnacg_results = search_wnacg_by_title(e_ex_hentai_title, main_title_parsed, subtitle_parsed, extra_japanese_main_title)

        # Step 4: 構建回覆消息
        response_text = "" 
        
        if nhentai_results:
            response_text += "✨ *Nhentai 相關作品 (相似度):*\n"
            for i, result in enumerate(nhentai_results):
                stars = "⭐" * int(result['similarity'] // 20)
                response_text += f"{i+1}. {result['url']} ({stars} {result['similarity']:.1f}%)\n" 
        else:
            response_text += "❌ *Nhentai 相關作品:* 未找到匹配結果。\n"

        response_text += "\n"

        if wnacg_results:
            response_text += "📚 *紳士漫畫相關作品 (標題匹配):*\n"
            for i, result in enumerate(wnacg_results):
                translated_tag = " (漢化版)" if result.get('is_translated', False) else ""
                response_text += f"{i+1}. {result['url']}{translated_tag}\n" 
        else:
            response_text += "❌ *紳士漫畫相關作品:* 未找到匹配結果。\n"

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text=response_text,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        PROCESSED_LINKS_CACHE[(chat_id, message_id)] = link

    except Exception as e:
        logger.error(f"處理 E-Hentai/ExHentai 連結時發生未預期錯誤: {e}\n{traceback.format_exc()}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text=f"哎呀！處理您的連結時發生了錯誤：`{str(e)}`",
            parse_mode='Markdown'
        )
        PROCESSED_LINKS_CACHE[(chat_id, message_id)] = link


# 重寫此函數，採用更明確的替換邏輯
async def handle_x_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 X.com (Twitter) 連結，轉換為 VxTwitter 連結。"""
    message = update.message
    if not message or not message.text:
        return

    chat_id = message.chat.id
    message_id = message.message_id

    # 使用全域定義的 x_link_regex 來提取訊息中的實際連結
    match = x_link_regex.search(message.text)
    if not match:
        logger.warning(f"處理器觸發但未在訊息中找到 X.com 或 Twitter.com 連結: {message.text}")
        return
        
    original_link = match.group(0).strip() # 提取匹配到的完整連結字串並去除前後空格

    if PROCESSED_LINKS_CACHE.get((chat_id, message_id)) == original_link:
        logger.info(f"訊息 {message_id} 已處理過 X.com 連結 {original_link}，跳過。")
        return

    try:
        logger.info(f"Original X.com/Twitter.com link received: {original_link}")

        new_url = ""
        # 檢查連結是否以 x.com 開頭
        if "x.com" in original_link.lower():
            new_url = original_link.replace("x.com", "vxtwitter.com")
        # 檢查連結是否以 twitter.com 開頭
        elif "twitter.com" in original_link.lower():
            new_url = original_link.replace("twitter.com", "vxtwitter.com")
        else:
            # 理論上，由於 regex 的過濾，這個分支不應該被觸發
            logger.warning(f"收到非預期的 X/Twitter 連結格式，未能轉換: {original_link}")
            await update.message.reply_text(
                f"無法轉換此連結：`{original_link}`。請確保它是標準的 X.com 或 Twitter.com 連結。",
                reply_to_message_id=message_id,
                parse_mode='Markdown'
            )
            return

        # 確保只有在成功生成 new_url 後才進行日誌記錄和回覆
        if new_url:
            logger.info(f"Converted VxTwitter link: {new_url}")

            await update.message.reply_text(
                f"已轉換為更好的預覽連結：\n{new_url}",
                reply_to_message_id=message_id,
                disable_web_page_preview=False
            )
            PROCESSED_LINKS_CACHE[(chat_id, message_id)] = original_link
            logger.info(f"X.com/Twitter.com 連結 {original_link} 已成功轉換並回傳連結 {new_url} 給 {message.from_user.id if message.from_user else '未知用戶'}")
    except Exception as e:
        logger.error(f"處理 X.com/Twitter.com 連結時發生未預期錯誤: {e}\n{traceback.format_exc()}")
        await update.message.reply_text(
            f"哎呀！處理您的 X.com/Twitter.com 連結時發生了錯誤：`{str(e)}`",
            reply_to_message_id=message_id,
            parse_mode='Markdown'
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理機器人運作中發生的所有錯誤。"""
    logger.error(f"更新 {update} 導致錯誤 {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "抱歉，機器人發生了一些內部錯誤。請稍後再試。",
            reply_to_message_id=update.effective_message.message_id
        )

def main() -> None:
    """主函數，啟動機器人。"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    
    # 處理新訊息（現在會智慧提取連結）
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(e_ex_hentai_regex), handle_e_ex_hentai_link))
    # Crucially, ensure the regex for x_link_regex *only* matches x.com or twitter.com
    # and not an already converted vxtwitter.com link, which would cause double conversion.
    # The current regex `r'https?://(?:x|twitter)\.com/\S+'` already handles this correctly,
    # as it doesn't match 'vxtwitter.com'.
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(x_link_regex), handle_x_link))

    application.add_error_handler(error_handler)

    logger.info("機器人已啟動，開始監聽訊息...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()