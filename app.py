import json
import random
import re
from datetime import datetime
from pathlib import Path
from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# 國中背單字網頁軟體
# 第三階段：
# 1. 記憶卡模式
# 2. 學習狀況 CSV 上傳 / 下載
# 3. 測驗模式：中翻英、英翻中
# 4. 答對熟練度 +1，答錯熟練度 -1
# 5. 精熟單字預設不出題，可勾選列入
# ============================================================

WORDS_FILE = "words.csv"

REQUIRED_COLUMNS = [
    "word_id",
    "grade",
    "semester",
    "unit_id",
    "unit_name",
    "word_order",
    "word",
    "part_of_speech",
    "chinese",
    "example_1_en",
    "example_1_zh",
    "example_2_en",
    "example_2_zh",
    "example_3_en",
    "example_3_zh",
]

GRADE_ORDER = ["國一先修", "國一", "國二", "國三"]
SEMESTER_ORDER = ["上學期", "下學期"]

LEVEL_LABELS = {
    0: "未記憶",
    1: "不熟",
    2: "有點熟",
    3: "很熟",
    4: "精熟",
}

QUIZ_LEVEL_WEIGHTS = {
    0: 100,  # 未記憶
    1: 70,   # 不熟
    2: 50,   # 有點熟
    3: 30,   # 很熟
    4: 10,   # 精熟；只有勾選「精熟單字也列入出題」時才使用
}


def quiz_weight_by_level(level, include_mastered: bool) -> int:
    """依熟練度決定測驗抽題權重。"""
    level = normalize_level(level)
    if level == 4 and not include_mastered:
        return 0
    return QUIZ_LEVEL_WEIGHTS.get(level, 100)


PROGRESS_COLUMNS = [
    "word_id",
    "c2e_level",
    "e2c_level",
    "c2e_correct",
    "c2e_wrong",
    "e2c_correct",
    "e2c_wrong",
    "last_reviewed",
]


# ============================================================
# 基礎工具
# ============================================================

def safe_int(value, default=9999):
    try:
        return int(value)
    except Exception:
        return default


def normalize_level(value):
    try:
        value = int(value)
    except Exception:
        value = 0
    return max(0, min(4, value))


def level_text(value):
    return LEVEL_LABELS.get(normalize_level(value), "未記憶")


def normalize_answer(text: str) -> str:
    """
    中翻英答案判斷用。
    原則：不處理同義字，只比對本題指定單字。
    但會忽略大小寫、前後空白、多餘空格與句尾 .!?。
    """
    text = str(text).strip().lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"\s+", " ", text)
    text = text.strip("。．.?!？！ ")
    return text


POS_ZH_MAP = {
    "n.": "名詞",
    "v.": "動詞",
    "adj.": "形容詞",
    "adv.": "副詞",
    "prep.": "介系詞",
    "conj.": "連接詞",
    "pron.": "代名詞",
    "aux.": "助動詞",
    "interj.": "感嘆詞",
    "phrase": "片語",
    "sentence": "句子",
}


def pos_with_chinese(pos_text: str) -> str:
    """
    將詞性顯示為「英文 / 中文」。
    例如：
    adj. -> adj. / 形容詞
    n. / adj. -> n. / 名詞；adj. / 形容詞
    """
    pos_text = str(pos_text).strip()
    if not pos_text:
        return ""

    parts = [p.strip() for p in re.split(r"/|；|;", pos_text) if p.strip()]
    display_parts = []

    for part in parts:
        zh = POS_ZH_MAP.get(part)
        if zh:
            display_parts.append(f"{part} / {zh}")
        else:
            display_parts.append(part)

    return "；".join(display_parts)



@st.cache_data
def load_words(path: str) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.exists():
        st.error(f"找不到 {path}，請把 words.csv 放在 app.py 同一個資料夾。")
        st.stop()

    df = pd.read_csv(file_path, dtype=str).fillna("")

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        st.error("words.csv 缺少欄位：" + "、".join(missing))
        st.stop()

    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    df["_grade_order"] = df["grade"].apply(
        lambda x: GRADE_ORDER.index(x) if x in GRADE_ORDER else 999
    )
    df["_semester_order"] = df["semester"].apply(
        lambda x: SEMESTER_ORDER.index(x) if x in SEMESTER_ORDER else 999
    )
    df["_word_order"] = df["word_order"].apply(safe_int)

    df = df.sort_values(
        by=["_grade_order", "_semester_order", "unit_id", "_word_order", "word"],
        kind="stable",
    ).reset_index(drop=True)

    return df


def create_default_progress(words_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "word_id": words_df["word_id"].astype(str),
        "c2e_level": 0,
        "e2c_level": 0,
        "c2e_correct": 0,
        "c2e_wrong": 0,
        "e2c_correct": 0,
        "e2c_wrong": 0,
        "last_reviewed": "",
    })


def prepare_progress(uploaded_file, words_df: pd.DataFrame) -> pd.DataFrame:
    default_progress = create_default_progress(words_df)

    if uploaded_file is None:
        progress = default_progress.copy()
    else:
        try:
            progress = pd.read_csv(uploaded_file, dtype=str).fillna("")
        except Exception:
            st.sidebar.error("學習狀況檔案讀取失敗，已改用全新進度。")
            progress = default_progress.copy()

    for col in PROGRESS_COLUMNS:
        if col not in progress.columns:
            progress[col] = ""

    progress = progress[PROGRESS_COLUMNS].copy()
    progress["word_id"] = progress["word_id"].astype(str).str.strip()
    progress = progress.drop_duplicates(subset=["word_id"], keep="last")

    # 以目前 words.csv 為主，舊進度檔缺少的新單字自動補入
    merged = default_progress[["word_id"]].merge(progress, on="word_id", how="left")

    for col in PROGRESS_COLUMNS:
        if col == "word_id":
            continue
        if col not in merged.columns:
            merged[col] = default_progress[col]

    numeric_cols = [
        "c2e_level", "e2c_level",
        "c2e_correct", "c2e_wrong",
        "e2c_correct", "e2c_wrong",
    ]

    for col in numeric_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).astype(int)

    merged["c2e_level"] = merged["c2e_level"].apply(normalize_level)
    merged["e2c_level"] = merged["e2c_level"].apply(normalize_level)
    merged["last_reviewed"] = merged["last_reviewed"].astype(str).replace("nan", "")

    return merged[PROGRESS_COLUMNS].copy()


def progress_to_csv_bytes(progress_df: pd.DataFrame) -> bytes:
    return progress_df[PROGRESS_COLUMNS].to_csv(index=False).encode("utf-8-sig")


def upload_signature(uploaded_file):
    if uploaded_file is None:
        return "__no_upload__"
    return f"{uploaded_file.name}_{uploaded_file.size}"


def init_or_load_progress(uploaded_file, words_df: pd.DataFrame):
    sig = upload_signature(uploaded_file)

    if "progress_df" not in st.session_state:
        st.session_state.progress_df = prepare_progress(uploaded_file, words_df)
        st.session_state.progress_upload_signature = sig

    # 有新上傳檔時，才重新讀取；避免測驗更新後 rerun 被重設
    if sig != st.session_state.get("progress_upload_signature"):
        st.session_state.progress_df = prepare_progress(uploaded_file, words_df)
        st.session_state.progress_upload_signature = sig


def get_progress_row(word_id: str) -> dict:
    progress_df = st.session_state.progress_df
    matched = progress_df[progress_df["word_id"] == word_id]
    if matched.empty:
        return {
            "c2e_level": 0,
            "e2c_level": 0,
            "c2e_correct": 0,
            "c2e_wrong": 0,
            "e2c_correct": 0,
            "e2c_wrong": 0,
            "last_reviewed": "",
        }
    return matched.iloc[0].to_dict()


def update_progress(word_id: str, direction: str, is_correct: bool):
    """
    direction:
    - c2e: 中翻英
    - e2c: 英翻中
    """
    progress_df = st.session_state.progress_df

    if word_id not in set(progress_df["word_id"]):
        new_row = {
            "word_id": word_id,
            "c2e_level": 0,
            "e2c_level": 0,
            "c2e_correct": 0,
            "c2e_wrong": 0,
            "e2c_correct": 0,
            "e2c_wrong": 0,
            "last_reviewed": "",
        }
        progress_df = pd.concat([progress_df, pd.DataFrame([new_row])], ignore_index=True)

    idx = progress_df.index[progress_df["word_id"] == word_id][0]

    if direction == "c2e":
        level_col = "c2e_level"
        correct_col = "c2e_correct"
        wrong_col = "c2e_wrong"
    else:
        level_col = "e2c_level"
        correct_col = "e2c_correct"
        wrong_col = "e2c_wrong"

    old_level = normalize_level(progress_df.at[idx, level_col])

    if is_correct:
        progress_df.at[idx, level_col] = min(4, old_level + 1)
        progress_df.at[idx, correct_col] = int(progress_df.at[idx, correct_col]) + 1
    else:
        progress_df.at[idx, level_col] = max(0, old_level - 1)
        progress_df.at[idx, wrong_col] = int(progress_df.at[idx, wrong_col]) + 1

    progress_df.at[idx, "last_reviewed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    st.session_state.progress_df = progress_df[PROGRESS_COLUMNS].copy()


def get_unit_options(df: pd.DataFrame):
    units = (
        df[["unit_id", "unit_name"]]
        .drop_duplicates()
        .sort_values(by=["unit_id", "unit_name"], kind="stable")
    )
    return [(f"{row['unit_id']}｜{row['unit_name']}", row["unit_id"]) for _, row in units.iterrows()]


def reset_card_index_if_filter_changed(signature: str):
    if "filter_signature" not in st.session_state:
        st.session_state.filter_signature = signature
        st.session_state.card_index = 0

    if st.session_state.filter_signature != signature:
        st.session_state.filter_signature = signature
        st.session_state.card_index = 0
        reset_quiz_state()


# ============================================================
# TTS / HTML 顯示
# ============================================================

def show_word_card(row: pd.Series, index: int, total: int):
    word_raw = row["word"]
    word = escape(word_raw)
    pos = escape(pos_with_chinese(row["part_of_speech"]))
    chinese = escape(row["chinese"])
    word_json = json.dumps(word_raw, ensure_ascii=False)

    card_html = f"""
    <div class="card">
        <div class="card-small">第 {index + 1} / {total} 張</div>

        <div class="word-row">
            <div class="word-title">{word}</div>
            <button class="speak-button" onclick="speakWord()">🔊 發音</button>
        </div>

        <div class="meaning-line">
            <span class="pos">{pos}</span>
            <span>{chinese}</span>
        </div>
    </div>

    <script>
    function speakWord() {{
        const text = {word_json};
        window.speechSynthesis.cancel();
        const msg = new SpeechSynthesisUtterance(text);
        msg.lang = "en-US";
        msg.rate = 0.85;
        msg.pitch = 1.0;
        window.speechSynthesis.speak(msg);
    }}
    </script>

    <style>
    body {{
        margin: 0;
        background: transparent;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .card {{
        box-sizing: border-box;
        width: 100%;
        border: 1px solid #435143;
        border-radius: 14px;
        padding: 0.82rem 1.05rem;
        background: #222821;
        color: #d8ddd6;
        box-shadow: 0 1px 0 rgba(0,0,0,0.12);
    }}
    .card-small {{
        color: #9aa69c;
        font-size: 0.9rem;
        margin-bottom: 0.35rem;
    }}
    .word-row {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        flex-wrap: wrap;
    }}
    .word-title {{
        color: #c7d8e6;
        font-size: 2.2rem;
        font-weight: 850;
        line-height: 1.12;
    }}
    .speak-button {{
        font-size: 0.95rem;
        font-weight: 700;
        padding: 0.32rem 0.72rem;
        border-radius: 10px;
        border: 1px solid #5b725b;
        cursor: pointer;
        background: #314336;
        color: #dce8de;
    }}
    .speak-button:hover {{
        background: #3a4f40;
    }}
    .meaning-line {{
        color: #d6d2c4;
        font-size: 1.08rem;
        margin-top: 0.5rem;
    }}
    .pos {{
        display: inline-block;
        font-weight: 850;
        color: #e1c27a;
        background: #3e3420;
        border: 1px solid #6d5b33;
        border-radius: 7px;
        padding: 0.08rem 0.38rem;
        margin-right: 0.5rem;
    }}
    </style>
    """

    components.html(card_html, height=132)


def show_examples(row: pd.Series):
    st.markdown('<div class="section-title">例句</div>', unsafe_allow_html=True)

    examples = []
    for i in range(1, 4):
        en_raw = row.get(f"example_{i}_en", "")
        zh_raw = row.get(f"example_{i}_zh", "")
        if en_raw or zh_raw:
            examples.append({
                "en_raw": en_raw,
                "en": escape(en_raw),
                "zh": escape(zh_raw),
            })

    if not examples:
        st.info("這個單字目前還沒有例句。")
        return

    example_items_html = ""
    for ex in examples:
        en_json = json.dumps(ex["en_raw"], ensure_ascii=False)
        example_items_html += f"""
        <div class="example-box">
            <div class="example-row">
                <button class="example-speak-button" onclick='speakExample({en_json})'>🔊</button>
                <div class="example-text">
                    <div class="example-en">{ex["en"]}</div>
                    <div class="example-zh">{ex["zh"]}</div>
                </div>
            </div>
        </div>
        """

    examples_height = 88 * len(examples) + 12
    examples_html = f"""
    <div class="examples-wrap">
        {example_items_html}
    </div>

    <script>
    function speakExample(text) {{
        window.speechSynthesis.cancel();
        const msg = new SpeechSynthesisUtterance(text);
        msg.lang = "en-US";
        msg.rate = 0.82;
        msg.pitch = 1.0;
        window.speechSynthesis.speak(msg);
    }}
    </script>

    <style>
    body {{
        margin: 0;
        background: transparent;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .examples-wrap {{
        width: 100%;
        box-sizing: border-box;
    }}
    .example-box {{
        box-sizing: border-box;
        width: 100%;
        border-left: 4px solid #5f8063;
        border-radius: 8px;
        padding: 0.48rem 0.72rem;
        margin-bottom: 0.52rem;
        background: #222821;
        color: #d8ddd6;
    }}
    .example-row {{
        display: flex;
        align-items: flex-start;
        gap: 0.62rem;
    }}
    .example-speak-button {{
        flex: 0 0 auto;
        margin-top: 0.02rem;
        font-size: 0.92rem;
        font-weight: 700;
        line-height: 1;
        padding: 0.34rem 0.43rem;
        border-radius: 9px;
        border: 1px solid #5b725b;
        cursor: pointer;
        background: #314336;
        color: #dce8de;
    }}
    .example-speak-button:hover {{
        background: #3a4f40;
    }}
    .example-text {{
        min-width: 0;
    }}
    .example-en {{
        font-size: 1.02rem;
        font-weight: 700;
        color: #a8c7d8;
        line-height: 1.35;
    }}
    .example-zh {{
        font-size: 0.95rem;
        color: #b9c3b7;
        margin-top: 0.18rem;
        line-height: 1.35;
    }}
    </style>
    """
    components.html(examples_html, height=examples_height)


def show_status(word_id: str):
    progress_row = get_progress_row(word_id)

    c2e = level_text(progress_row.get("c2e_level", 0))
    e2c = level_text(progress_row.get("e2c_level", 0))
    c2e_correct = int(progress_row.get("c2e_correct", 0))
    c2e_wrong = int(progress_row.get("c2e_wrong", 0))
    e2c_correct = int(progress_row.get("e2c_correct", 0))
    e2c_wrong = int(progress_row.get("e2c_wrong", 0))

    st.markdown('<div class="section-title compact-title">記憶狀況</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="status-box">
            <div>
                <span class="status-c2e">中翻英</span>：{c2e}
                <span class="status-count">答對 {c2e_correct}｜答錯 {c2e_wrong}</span>
            </div>
            <div>
                <span class="status-e2c">英翻中</span>：{e2c}
                <span class="status-count">答對 {e2c_correct}｜答錯 {e2c_wrong}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_sidebar_status(word_id: str):
    progress_row = get_progress_row(word_id)

    c2e = level_text(progress_row.get("c2e_level", 0))
    e2c = level_text(progress_row.get("e2c_level", 0))
    c2e_correct = int(progress_row.get("c2e_correct", 0))
    c2e_wrong = int(progress_row.get("c2e_wrong", 0))
    e2c_correct = int(progress_row.get("e2c_correct", 0))
    e2c_wrong = int(progress_row.get("e2c_wrong", 0))

    st.sidebar.markdown("### 記憶狀況")
    st.sidebar.markdown(
        f"""
        <div class="sidebar-status-box">
            <div>
                <span class="status-c2e">中翻英</span>：{c2e}<br>
                <span class="sidebar-status-count">答對 {c2e_correct}｜答錯 {c2e_wrong}</span>
            </div>
            <div style="margin-top:0.45rem;">
                <span class="status-e2c">英翻中</span>：{e2c}<br>
                <span class="sidebar-status-count">答對 {e2c_correct}｜答錯 {e2c_wrong}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_memory_card(row: pd.Series, index: int, total: int):
    show_word_card(row, index, total)
    show_examples(row)


def show_speak_button_inline(text: str, button_label="🔊 發音", height=46):
    text_json = json.dumps(text, ensure_ascii=False)
    html = f"""
    <button class="inline-speak" onclick="speakText()">{button_label}</button>

    <script>
    function speakText() {{
        const text = {text_json};
        window.speechSynthesis.cancel();
        const msg = new SpeechSynthesisUtterance(text);
        msg.lang = "en-US";
        msg.rate = 0.85;
        msg.pitch = 1.0;
        window.speechSynthesis.speak(msg);
    }}
    </script>

    <style>
    body {{
        margin: 0;
        background: transparent;
    }}
    .inline-speak {{
        font-size: 0.96rem;
        font-weight: 700;
        padding: 0.34rem 0.72rem;
        border-radius: 10px;
        border: 1px solid #5b725b;
        cursor: pointer;
        background: #314336;
        color: #dce8de;
    }}
    .inline-speak:hover {{
        background: #3a4f40;
    }}
    </style>
    """
    components.html(html, height=height)


# ============================================================
# 測驗模式
# ============================================================

def reset_quiz_state():
    for key in [
        "quiz_word_id",
        "quiz_signature",
        "quiz_answered",
        "quiz_result",
        "quiz_show_answer",
        "quiz_last_answer",
        "quiz_nonce",
    ]:
        if key in st.session_state:
            del st.session_state[key]


def pick_quiz_word(candidate_df: pd.DataFrame):
    if candidate_df.empty:
        st.session_state.quiz_word_id = None
        return

    if "quiz_weight" in candidate_df.columns and candidate_df["quiz_weight"].sum() > 0:
        row = candidate_df.sample(1, weights="quiz_weight").iloc[0]
    else:
        row = candidate_df.sample(1).iloc[0]

    st.session_state.quiz_word_id = row["word_id"]
    st.session_state.quiz_answered = False
    st.session_state.quiz_result = None
    st.session_state.quiz_show_answer = False
    st.session_state.quiz_last_answer = ""
    st.session_state.quiz_nonce = st.session_state.get("quiz_nonce", 0) + 1


def ensure_quiz_word(candidate_df: pd.DataFrame, signature: str):
    if st.session_state.get("quiz_signature") != signature:
        st.session_state.quiz_signature = signature
        pick_quiz_word(candidate_df)

    if "quiz_word_id" not in st.session_state:
        pick_quiz_word(candidate_df)

    if st.session_state.get("quiz_word_id") is None and not candidate_df.empty:
        pick_quiz_word(candidate_df)

    # 如果目前題目不在候選範圍內，換一題
    if not candidate_df.empty and st.session_state.get("quiz_word_id") not in set(candidate_df["word_id"]):
        pick_quiz_word(candidate_df)



def attach_progress(filtered_df: pd.DataFrame) -> pd.DataFrame:
    """把目前選擇範圍的單字表接上學習狀況。"""
    progress = st.session_state.progress_df.copy()
    merged = filtered_df.merge(
        progress[["word_id", "c2e_level", "e2c_level"]],
        on="word_id",
        how="left",
    )
    merged["c2e_level"] = pd.to_numeric(merged["c2e_level"], errors="coerce").fillna(0).astype(int)
    merged["e2c_level"] = pd.to_numeric(merged["e2c_level"], errors="coerce").fillna(0).astype(int)
    merged["both_mastered"] = (merged["c2e_level"] >= 4) & (merged["e2c_level"] >= 4)
    return merged


def build_memory_cards(filtered_df: pd.DataFrame, hide_mastered_cards: bool) -> pd.DataFrame:
    """
    記憶卡模式用。
    hide_mastered_cards=True 時，隱藏中翻英與英翻中都達精熟的單字。
    """
    merged = attach_progress(filtered_df)
    if hide_mastered_cards:
        merged = merged[~merged["both_mastered"]]
    return merged.reset_index(drop=True)


def level_count_text(series: pd.Series) -> str:
    """產生熟練度統計文字，順序由精熟到未記憶。"""
    series = pd.to_numeric(series, errors="coerce").fillna(0).astype(int)
    counts = series.value_counts().to_dict()
    order = [4, 3, 2, 1, 0]
    return "｜".join([f"{LEVEL_LABELS[level]} {int(counts.get(level, 0))}" for level in order])


def show_range_progress_summary(filtered_df: pd.DataFrame, in_sidebar: bool = False):
    """顯示目前選擇範圍的學習狀況統計。"""
    merged = attach_progress(filtered_df)

    c2e_summary = level_count_text(merged["c2e_level"])
    e2c_summary = level_count_text(merged["e2c_level"])
    both_mastered = int(merged["both_mastered"].sum())

    html = f"""
    <div class="range-summary">
        <div><span class="range-title">目前學習狀況</span></div>
        <div><span class="status-c2e">中翻英</span>：{c2e_summary}</div>
        <div><span class="status-e2c">英翻中</span>：{e2c_summary}</div>
        <div><span class="range-note">雙向都精熟：{both_mastered} 個</span></div>
    </div>
    """

    if in_sidebar:
        st.sidebar.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)



def build_quiz_candidates(filtered_df: pd.DataFrame, direction: str, include_mastered: bool) -> pd.DataFrame:
    merged = attach_progress(filtered_df)

    level_col = "c2e_level" if direction == "c2e" else "e2c_level"
    merged["quiz_weight"] = merged[level_col].apply(
        lambda level: quiz_weight_by_level(level, include_mastered)
    )

    # 未勾選精熟時，精熟字權重為 0，因此排除。
    merged = merged[merged["quiz_weight"] > 0]

    return merged.reset_index(drop=True)


def get_current_quiz_row(candidate_df: pd.DataFrame):
    word_id = st.session_state.get("quiz_word_id")
    matched = candidate_df[candidate_df["word_id"] == word_id]
    if matched.empty:
        return None
    return matched.iloc[0]


def show_c2e_quiz(row: pd.Series):
    st.markdown('<div class="quiz-card">', unsafe_allow_html=True)
    st.markdown('<div class="quiz-label">中翻英</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="quiz-question">
            <span class="quiz-pos">{escape(pos_with_chinese(row['part_of_speech']))}</span>
            <span class="quiz-chinese">{escape(row['chinese'])}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    show_speak_button_inline(row["word"], "🔊 聽單字")

    input_key = f"c2e_input_{row['word_id']}_{st.session_state.get('quiz_nonce', 0)}"
    user_answer = st.text_input("請輸入英文", key=input_key)

    col1, col2 = st.columns([1, 1])
    with col1:
        submit = st.button("送出答案", use_container_width=True, disabled=st.session_state.get("quiz_answered", False))
    with col2:
        if st.button("換一題", use_container_width=True):
            st.session_state.force_next_question = True
            st.rerun()

    if submit:
        correct_answer = row["word"]
        is_correct = normalize_answer(user_answer) == normalize_answer(correct_answer)
        update_progress(row["word_id"], "c2e", is_correct)
        st.session_state.quiz_answered = True
        st.session_state.quiz_result = is_correct
        st.session_state.quiz_last_answer = user_answer
        st.rerun()

    if st.session_state.get("quiz_answered", False):
        is_correct = st.session_state.get("quiz_result")
        last_answer = st.session_state.get("quiz_last_answer", "")

        if is_correct:
            st.success("答對了，熟練度 +1。")
        else:
            st.error("答錯了，熟練度 -1。")

        st.markdown(
            f"""
            <div class="answer-box">
                你的答案：<span class="answer-user">{escape(last_answer)}</span><br>
                正確答案：<span class="answer-correct">{escape(row["word"])}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("下一題", use_container_width=True):
            st.session_state.force_next_question = True
            st.rerun()



def show_e2c_quiz(row: pd.Series):
    word = escape(row["word"])
    st.markdown('<div class="quiz-card">', unsafe_allow_html=True)
    st.markdown('<div class="quiz-label">英翻中</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="quiz-word">{word}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    show_speak_button_inline(row["word"], "🔊 發音")

    if not st.session_state.get("quiz_show_answer", False):
        if st.button("公布答案", use_container_width=True):
            st.session_state.quiz_show_answer = True
            st.rerun()
    else:
        st.markdown(
            f"""
            <div class="answer-box">
                <span class="quiz-pos">{escape(pos_with_chinese(row['part_of_speech']))}</span>
                <span class="quiz-chinese">{escape(row['chinese'])}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            correct_click = st.button("我答對了", use_container_width=True, disabled=st.session_state.get("quiz_answered", False))
        with col2:
            wrong_click = st.button("我答錯了", use_container_width=True, disabled=st.session_state.get("quiz_answered", False))

        if correct_click:
            update_progress(row["word_id"], "e2c", True)
            st.session_state.quiz_answered = True
            st.session_state.quiz_result = True
            st.rerun()

        if wrong_click:
            update_progress(row["word_id"], "e2c", False)
            st.session_state.quiz_answered = True
            st.session_state.quiz_result = False
            st.rerun()

        if st.session_state.get("quiz_answered", False):
            if st.session_state.get("quiz_result"):
                st.success("已記錄：答對，熟練度 +1。")
            else:
                st.error("已記錄：答錯，熟練度 -1。")

            if st.button("下一題", use_container_width=True):
                st.session_state.force_next_question = True
                st.rerun()



# ============================================================
# Streamlit 主程式
# ============================================================

st.set_page_config(
    page_title="國中背單字系統",
    page_icon="📘",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --soft-card: #222821;
        --soft-card-2: #20261f;
        --soft-line: #3d4a3c;
        --word-color: #c7d8e6;
        --pos-color: #e1c27a;
        --zh-color: #d6d2c4;
        --en-example: #a8c7d8;
        --zh-example: #b9c3b7;
        --status-c2e: #d6b36a;
        --status-e2c: #8fc4a7;
    }

    .main-title {
        font-size: 2rem;
        font-weight: 800;
        margin-bottom: 0.25rem;
    }

    .sub-title {
        color: #8f9694;
        margin-bottom: 1rem;
    }

    .footer-note {
        color: #7f8784;
        font-size: 0.9rem;
        margin-top: 1.2rem;
        padding-top: 0.75rem;
        border-top: 1px solid #273027;
    }

    .sidebar-status-box {
        border: 1px solid #314033;
        border-radius: 10px;
        padding: 0.65rem 0.8rem;
        background: #1c221c;
        color: #c9d0cb;
        font-size: 0.95rem;
        line-height: 1.6;
        margin-top: 0.2rem;
        margin-bottom: 0.2rem;
    }

    .sidebar-status-count {
        color: #8f9694;
        font-size: 0.83rem;
    }

    .section-title {
        font-size: 1.18rem;
        font-weight: 800;
        margin-top: 0.75rem;
        margin-bottom: 0.42rem;
        color: #c9d0cb;
    }

    .compact-title {
        margin-top: 0.35rem;
    }

    .status-box {
        border: 1px solid var(--soft-line);
        border-radius: 10px;
        padding: 0.58rem 0.85rem;
        background: var(--soft-card-2);
        color: #d8ddd6;
        font-size: 0.97rem;
        line-height: 1.7;
    }

    .status-c2e {
        color: var(--status-c2e);
        font-weight: 800;
    }

    .status-e2c {
        color: var(--status-e2c);
        font-weight: 800;
    }

    .status-count {
        color: #8f9694;
        font-size: 0.86rem;
        margin-left: 0.7rem;
    }

    .range-summary {
        border: 1px solid #314033;
        border-radius: 10px;
        padding: 0.58rem 0.8rem;
        background: #1c221c;
        color: #c9d0cb;
        font-size: 0.92rem;
        line-height: 1.7;
        margin-top: 0.35rem;
        margin-bottom: 0.65rem;
    }

    .range-title {
        color: #c9d0cb;
        font-weight: 850;
    }

    .range-note {
        color: #8f9694;
        font-size: 0.86rem;
    }

    .quiz-card {
        border: 1px solid #435143;
        border-radius: 14px;
        padding: 0.95rem 1.05rem;
        background: #222821;
        color: #d8ddd6;
        margin-bottom: 0.65rem;
    }

    .quiz-label {
        font-size: 0.95rem;
        color: #9aa69c;
        margin-bottom: 0.35rem;
    }

    .quiz-question {
        font-size: 1.35rem;
        line-height: 1.45;
    }

    .quiz-word {
        color: #c7d8e6;
        font-size: 2.3rem;
        font-weight: 850;
        line-height: 1.15;
    }

    .quiz-pos {
        display: inline-block;
        font-weight: 850;
        color: #e1c27a;
        background: #3e3420;
        border: 1px solid #6d5b33;
        border-radius: 7px;
        padding: 0.08rem 0.38rem;
        margin-right: 0.5rem;
    }

    .quiz-chinese {
        color: #d6d2c4;
        font-weight: 650;
    }

    .answer-box {
        border: 1px solid #435143;
        border-radius: 10px;
        padding: 0.7rem 0.85rem;
        background: #20261f;
        color: #d8ddd6;
        line-height: 1.8;
        margin-top: 0.5rem;
        margin-bottom: 0.6rem;
    }

    .answer-user {
        color: #d6d2c4;
        font-weight: 700;
    }

    .answer-correct {
        color: #8fc4a7;
        font-weight: 850;
    }

    div[data-baseweb="tag"] {
        background-color: #3d5743 !important;
        color: #e7eee8 !important;
        border-radius: 8px !important;
    }

    div[data-baseweb="tag"] span {
        color: #e7eee8 !important;
    }

    div.stButton > button {
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

df = load_words(WORDS_FILE)

st.sidebar.title("📘 背單字系統")

mode = st.sidebar.radio(
    "模式",
    ["記憶模式", "測驗模式-英翻中", "測驗模式-中翻英"],
    index=0,
)

if mode != "記憶模式":
    include_mastered = st.sidebar.checkbox(
        "精熟單字也列入出題",
        value=False,
        key="include_mastered_sidebar",
    )
    st.sidebar.caption(
        "中翻英會自動判斷答案；英翻中會先公布答案，再由學生自評答對或答錯。"
    )

st.sidebar.divider()
st.sidebar.subheader("學習狀況")

uploaded_progress_file = st.sidebar.file_uploader(
    "上傳學習狀況 CSV",
    type=["csv"],
    help="可上傳上次下載的 progress.csv。"
)

init_or_load_progress(uploaded_progress_file, df)

st.sidebar.download_button(
    label="下載學習狀況 CSV",
    data=progress_to_csv_bytes(st.session_state.progress_df),
    file_name="progress.csv",
    mime="text/csv",
    use_container_width=True,
)

if uploaded_progress_file is None:
    st.sidebar.caption("目前使用目前工作階段的學習狀況。")
else:
    st.sidebar.caption("已載入上傳的學習狀況。")

st.sidebar.divider()

available_grades = [g for g in GRADE_ORDER if g in set(df["grade"])]
other_grades = sorted([g for g in df["grade"].unique() if g not in GRADE_ORDER and g])
grade_options = available_grades + other_grades

if not grade_options:
    st.error("words.csv 沒有可用的 grade 資料。")
    st.stop()

selected_grade = st.sidebar.selectbox("年級 / 階段", grade_options)

filtered = df[df["grade"] == selected_grade].copy()

selected_semester = ""
if selected_grade == "國一先修":
    st.sidebar.caption("國一先修不分上、下學期，直接選單元。")
else:
    semester_options = [s for s in SEMESTER_ORDER if s in set(filtered["semester"])]
    other_semesters = sorted([s for s in filtered["semester"].unique() if s not in SEMESTER_ORDER and s])
    semester_options = semester_options + other_semesters

    if not semester_options:
        st.sidebar.error("這個年級目前沒有上學期 / 下學期資料。")
        st.stop()

    selected_semester = st.sidebar.selectbox("學期", semester_options)
    filtered = filtered[filtered["semester"] == selected_semester].copy()

unit_options = get_unit_options(filtered)
unit_labels = [x[0] for x in unit_options]
label_to_unit_id = {label: unit_id for label, unit_id in unit_options}

if not unit_options:
    st.sidebar.error("目前選擇範圍內沒有單元資料。")
    st.stop()

ALL_UNITS_LABEL = "全部單元"
unit_labels_with_all = unit_labels + [ALL_UNITS_LABEL]

default_unit_selection = [unit_labels[0]] if unit_labels else []

selected_unit_labels = st.sidebar.multiselect(
    "單元，可複選",
    unit_labels_with_all,
    default=default_unit_selection,
)

if ALL_UNITS_LABEL in selected_unit_labels:
    selected_unit_ids = [unit_id for _, unit_id in unit_options]
else:
    selected_unit_ids = [label_to_unit_id[label] for label in selected_unit_labels if label in label_to_unit_id]

if not selected_unit_ids:
    st.warning("請先在左側選擇至少一個單元。")
    st.stop()

filtered = filtered[filtered["unit_id"].isin(selected_unit_ids)].reset_index(drop=True)

base_signature = f"{mode}|{selected_grade}|{selected_semester}|{','.join(selected_unit_ids)}"
reset_card_index_if_filter_changed(base_signature)

st.markdown('<div class="main-title">國中背單字系統｜第三階段</div>', unsafe_allow_html=True)
if filtered.empty:
    st.warning("目前選擇範圍沒有單字。")
    st.stop()


# ============================================================
# 記憶模式
# ============================================================

if mode == "記憶模式":
    st.sidebar.divider()
    st.sidebar.subheader("記憶卡設定")
    hide_mastered_cards = st.sidebar.checkbox(
        "精熟字卡不顯示",
        value=False,
        help="隱藏中翻英與英翻中都已達精熟的單字。"
    )

    memory_df = build_memory_cards(filtered, hide_mastered_cards)

    if memory_df.empty:
        st.sidebar.divider()
        show_range_progress_summary(filtered, in_sidebar=True)
        st.success("目前沒有可顯示的字卡。若要查看精熟字卡，請取消勾選「精熟字卡不顯示」。")
        st.stop()

    if st.session_state.card_index >= len(memory_df):
        st.session_state.card_index = 0

    control_cols = st.columns([1.15, 1.15, 1.05, 4.2])

    with control_cols[0]:
        if st.button("⬅ 上一張", use_container_width=True):
            st.session_state.card_index = (st.session_state.card_index - 1) % len(memory_df)
            st.rerun()

    with control_cols[1]:
        if st.button("➡ 下一張", use_container_width=True):
            st.session_state.card_index = (st.session_state.card_index + 1) % len(memory_df)
            st.rerun()

    with control_cols[2]:
        if st.button("🎲 隨機", use_container_width=True):
            st.session_state.card_index = random.randint(0, len(memory_df) - 1)
            st.rerun()

    with control_cols[3]:
        if hide_mastered_cards:
            hidden_count = len(filtered) - len(memory_df)
            st.caption(f"目前選擇範圍共有 {len(filtered)} 個單字；已隱藏雙向精熟 {hidden_count} 個；顯示 {len(memory_df)} 個")
        else:
            st.caption(f"目前選擇範圍共有 {len(filtered)} 個單字；顯示 {len(memory_df)} 個")

    current_row = memory_df.iloc[st.session_state.card_index]

    st.sidebar.divider()
    show_sidebar_status(current_row["word_id"])
    show_range_progress_summary(filtered, in_sidebar=True)

    show_memory_card(current_row, st.session_state.card_index, len(memory_df))

    with st.expander("查看目前選擇範圍的單字表"):
        st.dataframe(
            memory_df[
                [
                    "word_id",
                    "grade",
                    "semester",
                    "unit_id",
                    "unit_name",
                    "word_order",
                    "word",
                    "part_of_speech",
                    "chinese",
                    "c2e_level",
                    "e2c_level",
                ]
            ].assign(
                詞性=lambda x: x["part_of_speech"].apply(pos_with_chinese),
                中翻英=lambda x: x["c2e_level"].apply(level_text),
                英翻中=lambda x: x["e2c_level"].apply(level_text),
            ).drop(columns=["part_of_speech", "c2e_level", "e2c_level"]),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# 測驗模式
# ============================================================

else:
    if mode == "測驗模式-中翻英":
        direction = "c2e"
        quiz_direction_label = "中翻英"
    else:
        direction = "e2c"
        quiz_direction_label = "英翻中"

    candidate_df = build_quiz_candidates(filtered, direction, include_mastered)

    quiz_signature = (
        f"{base_signature}|{direction}|include_mastered={include_mastered}|"
        f"candidate_count={len(candidate_df)}"
    )

    # 使用者按「換一題」或「下一題」時，先換題
    if st.session_state.get("force_next_question", False):
        st.session_state.force_next_question = False
        pick_quiz_word(candidate_df)

    ensure_quiz_word(candidate_df, quiz_signature)

    st.markdown(
        f'<div class="section-title">目前模式：測驗模式－{quiz_direction_label}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"目前測驗範圍：{len(filtered)} 個單字；"
        f"可出題：{len(candidate_df)} 個。"
        + (" 已包含精熟單字。" if include_mastered else " 精熟單字預設不出題。")
    )
    st.caption(
        "出題權重：未記憶 100｜不熟 70｜有點熟 50｜很熟 30"
        + ("｜精熟 10" if include_mastered else "｜精熟 0")
    )

    if candidate_df.empty:
        st.success("目前沒有可出題單字。可以勾選「精熟單字也列入出題」，或改選其他單元。")
        st.stop()

    current_quiz_row = get_current_quiz_row(candidate_df)

    if current_quiz_row is None:
        pick_quiz_word(candidate_df)
        current_quiz_row = get_current_quiz_row(candidate_df)

    if current_quiz_row is None:
        st.warning("暫時找不到題目，請重新整理頁面。")
        st.stop()

    st.sidebar.divider()
    show_sidebar_status(current_quiz_row["word_id"])
    show_range_progress_summary(filtered, in_sidebar=True)

    if direction == "c2e":
        show_c2e_quiz(current_quiz_row)
    else:
        show_e2c_quiz(current_quiz_row)

    with st.expander("查看目前測驗範圍的單字表"):
        display_df = candidate_df[
            [
                "word_id",
                "unit_id",
                "word_order",
                "word",
                "part_of_speech",
                "chinese",
                "c2e_level",
                "e2c_level",
                "quiz_weight",
            ]
        ].copy()
        display_df["詞性"] = display_df["part_of_speech"].apply(pos_with_chinese)
        display_df["中翻英"] = display_df["c2e_level"].apply(level_text)
        display_df["英翻中"] = display_df["e2c_level"].apply(level_text)
        display_df["出題權重"] = display_df["quiz_weight"]
        display_df = display_df.drop(columns=["part_of_speech", "c2e_level", "e2c_level", "quiz_weight"])
        st.dataframe(display_df, use_container_width=True, hide_index=True)


st.markdown(
    '<div class="footer-note">目前功能：記憶卡、熟練度統計、精熟字卡隱藏、學習狀況上傳 / 下載、左側測驗模式切換。</div>',
    unsafe_allow_html=True,
)

