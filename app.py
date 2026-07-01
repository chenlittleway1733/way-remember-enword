import json
import random
from pathlib import Path
from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# 國中背單字網頁軟體｜第一階段
# 功能：
# 1. 讀取 words.csv
# 2. 左側選年級 / 學期 / 單元
# 3. 右側顯示單字卡
# 4. 上一張 / 下一張 / 隨機
# 5. 瀏覽器 TTS 發音
#
# 尚未加入：
# - 學習狀況 CSV
# - 測驗模式
# - 熟練度升降
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


def safe_int(value, default=9999):
    """把排序欄位轉成整數；失敗時放到後面。"""
    try:
        return int(value)
    except Exception:
        return default


@st.cache_data
def load_words(path: str) -> pd.DataFrame:
    """讀取單字 CSV。"""
    file_path = Path(path)
    if not file_path.exists():
        st.error(f"找不到 {path}，請把 words.csv 放在 app.py 同一個資料夾。")
        st.stop()

    df = pd.read_csv(file_path, dtype=str).fillna("")

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        st.error("words.csv 缺少欄位：" + "、".join(missing))
        st.stop()

    # 清理空白
    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    # 排序
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


def speak_button(text: str, label: str = "🔊 發音"):
    """
    使用瀏覽器內建 speechSynthesis 發音。
    注意：這是第一階段簡易作法，使用 Streamlit components 嵌入 HTML/JS。
    """
    text_json = json.dumps(text, ensure_ascii=False)

    html = f"""
    <button
        onclick="speakWord()"
        style="
            font-size: 16px;
            padding: 0.45rem 0.8rem;
            border-radius: 8px;
            border: 1px solid #ddd;
            cursor: pointer;
            background: #ffffff;
        "
    >
        {label}
    </button>

    <script>
    function speakWord() {{
        const text = {text_json};
        window.speechSynthesis.cancel();
        const msg = new SpeechSynthesisUtterance(text);
        msg.lang = "en-US";
        msg.rate = 0.85;
        msg.pitch = 1.0;
        window.speechSynthesis.speak(msg);
    }}
    </script>
    """
    components.html(html, height=45)


def get_unit_options(df: pd.DataFrame):
    """回傳單元選項：[(顯示文字, unit_id), ...]。"""
    units = (
        df[["unit_id", "unit_name"]]
        .drop_duplicates()
        .sort_values(by=["unit_id", "unit_name"], kind="stable")
    )

    options = []
    for _, row in units.iterrows():
        unit_id = row["unit_id"]
        unit_name = row["unit_name"]
        label = f"{unit_id}｜{unit_name}"
        options.append((label, unit_id))

    return options


def reset_card_index_if_filter_changed(signature: str):
    """如果左側選擇條件改變，重設目前卡片位置。"""
    if "filter_signature" not in st.session_state:
        st.session_state.filter_signature = signature
        st.session_state.card_index = 0

    if st.session_state.filter_signature != signature:
        st.session_state.filter_signature = signature
        st.session_state.card_index = 0


def show_card(row: pd.Series, index: int, total: int):
    """顯示右側單字卡。"""
    word_raw = row["word"]
    word = escape(word_raw)
    pos = escape(row["part_of_speech"])
    chinese = escape(row["chinese"])
    word_json = json.dumps(word_raw, ensure_ascii=False)

    # 用 components.html 做單字卡，才能把瀏覽器 TTS 按鈕放在英文單字右邊。
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
        border: 1px solid #cfd8ca;
        border-radius: 14px;
        padding: 0.82rem 1.05rem;
        background: #eef1e8;
        color: #111111;
        box-shadow: 0 1px 0 rgba(0,0,0,0.04);
    }}
    .card-small {{
        color: #66736b;
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
        color: #20344a;
        font-size: 2.2rem;
        font-weight: 850;
        line-height: 1.12;
    }}
    .speak-button {{
        font-size: 0.95rem;
        font-weight: 700;
        padding: 0.32rem 0.72rem;
        border-radius: 10px;
        border: 1px solid #adbba7;
        cursor: pointer;
        background: #dde7d8;
        color: #20344a;
    }}
    .speak-button:hover {{
        background: #d1decb;
    }}
    .meaning-line {{
        color: #2f3b35;
        font-size: 1.08rem;
        margin-top: 0.5rem;
    }}
    .pos {{
        display: inline-block;
        font-weight: 850;
        color: #6f4b15;
        background: #ead9b5;
        border-radius: 7px;
        padding: 0.08rem 0.38rem;
        margin-right: 0.5rem;
    }}
    </style>
    """

    components.html(card_html, height=132)

    st.markdown('<div class="section-title">例句</div>', unsafe_allow_html=True)

    has_example = False
    for i in range(1, 4):
        en = escape(row.get(f"example_{i}_en", ""))
        zh = escape(row.get(f"example_{i}_zh", ""))

        if en or zh:
            has_example = True
            st.markdown(
                f"""
                <div class="example-box">
                    <div class="example-en">{en}</div>
                    <div class="example-zh">{zh}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if not has_example:
        st.info("這個單字目前還沒有例句。")

    st.markdown('<div class="section-title">記憶狀況</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="status-box">
            <span class="status-c2e">中翻英</span>：未記憶<br>
            <span class="status-e2c">英翻中</span>：未記憶
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# Streamlit 主程式
# ============================================================

st.set_page_config(
    page_title="國中背單字系統｜第一階段",
    page_icon="📘",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --soft-card: #eef1e8;
        --soft-card-2: #e9eee7;
        --soft-line: #cfd8ca;
        --word-color: #20344a;
        --pos-color: #6f4b15;
        --zh-color: #2f3b35;
        --en-example: #1f4f69;
        --zh-example: #52625a;
        --status-c2e: #80541d;
        --status-e2c: #286050;
    }

    .main-title {
        font-size: 2rem;
        font-weight: 800;
        margin-bottom: 0.25rem;
    }

    .sub-title {
        color: #9ca3af;
        margin-bottom: 1rem;
    }

    .section-title {
        font-size: 1.35rem;
        font-weight: 800;
        margin-top: 1.1rem;
        margin-bottom: 0.55rem;
        color: #e5e7eb;
    }

    .example-box {
        border-left: 5px solid #9db5a3;
        border-radius: 8px;
        padding: 0.52rem 0.8rem;
        margin-bottom: 0.52rem;
        background: var(--soft-card);
        color: #111111;
    }

    .example-en {
        font-size: 1.03rem;
        font-weight: 700;
        color: var(--en-example);
    }

    .example-zh {
        font-size: 0.96rem;
        color: var(--zh-example);
        margin-top: 0.2rem;
    }

    .status-box {
        border: 1px solid var(--soft-line);
        border-radius: 10px;
        padding: 0.58rem 0.85rem;
        background: var(--soft-card-2);
        color: #111111;
        font-size: 0.98rem;
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

    /* 左側多選標籤：降低紅色刺激感 */
    div[data-baseweb="tag"] {
        background-color: #586b5b !important;
        color: #f5f7f2 !important;
        border-radius: 8px !important;
    }

    div[data-baseweb="tag"] span {
        color: #f5f7f2 !important;
    }

    /* 上方按鈕文字盡量不換行 */
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
    ["記憶模式", "測驗模式（第二階段加入）"],
    index=0,
)

if mode != "記憶模式":
    st.sidebar.warning("第一階段先完成記憶卡。測驗模式會在第二階段加入。")

# 年級選擇
available_grades = [g for g in GRADE_ORDER if g in set(df["grade"])]
other_grades = sorted([g for g in df["grade"].unique() if g not in GRADE_ORDER and g])
grade_options = available_grades + other_grades

if not grade_options:
    st.error("words.csv 沒有可用的 grade 資料。")
    st.stop()

selected_grade = st.sidebar.selectbox("年級 / 階段", grade_options)

# 國一先修沒有學期；國一～國三才有學期
filtered = df[df["grade"] == selected_grade].copy()

if selected_grade == "國一先修":
    st.sidebar.caption("國一先修不分上、下學期，直接選單元。")
else:
    semester_options = [
        s for s in SEMESTER_ORDER if s in set(filtered["semester"])
    ]
    other_semesters = sorted(
        [s for s in filtered["semester"].unique() if s not in SEMESTER_ORDER and s]
    )
    semester_options = semester_options + other_semesters

    if not semester_options:
        st.sidebar.error("這個年級目前沒有上學期 / 下學期資料。")
        st.stop()

    selected_semester = st.sidebar.selectbox("學期", semester_options)
    filtered = filtered[filtered["semester"] == selected_semester].copy()

# 單元複選
unit_options = get_unit_options(filtered)
unit_labels = [x[0] for x in unit_options]
label_to_unit_id = {label: unit_id for label, unit_id in unit_options}

if not unit_options:
    st.sidebar.error("目前選擇範圍內沒有單元資料。")
    st.stop()

selected_unit_labels = st.sidebar.multiselect(
    "單元，可複選",
    unit_labels,
    default=unit_labels,
)

selected_unit_ids = [label_to_unit_id[label] for label in selected_unit_labels]

if not selected_unit_ids:
    st.warning("請先在左側選擇至少一個單元。")
    st.stop()

filtered = filtered[filtered["unit_id"].isin(selected_unit_ids)].reset_index(drop=True)

signature = f"{selected_grade}|{','.join(selected_unit_ids)}"
if selected_grade != "國一先修":
    signature += f"|{selected_semester}"

reset_card_index_if_filter_changed(signature)

# 主畫面
st.markdown('<div class="main-title">國中背單字系統｜第一階段</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">目前功能：單元篩選、單字卡、例句、英文單字旁發音、上一張 / 下一張 / 隨機。</div>',
    unsafe_allow_html=True,
)

if filtered.empty:
    st.warning("目前選擇範圍沒有單字。")
    st.stop()

# 避免 index 超出範圍
if st.session_state.card_index >= len(filtered):
    st.session_state.card_index = 0

control_cols = st.columns([1.15, 1.15, 1.05, 4.2])

with control_cols[0]:
    if st.button("⬅ 上一張", use_container_width=True):
        st.session_state.card_index = (st.session_state.card_index - 1) % len(filtered)
        st.rerun()

with control_cols[1]:
    if st.button("➡ 下一張", use_container_width=True):
        st.session_state.card_index = (st.session_state.card_index + 1) % len(filtered)
        st.rerun()

with control_cols[2]:
    if st.button("🎲 隨機", use_container_width=True):
        st.session_state.card_index = random.randint(0, len(filtered) - 1)
        st.rerun()

with control_cols[3]:
    st.caption(f"目前選擇範圍共有 {len(filtered)} 個單字")

current_row = filtered.iloc[st.session_state.card_index]
show_card(current_row, st.session_state.card_index, len(filtered))

with st.expander("查看目前選擇範圍的單字表"):
    st.dataframe(
        filtered[
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
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
