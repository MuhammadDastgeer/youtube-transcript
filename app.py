import streamlit as st
import pandas as pd
import re
import io
import zipfile
from collections import Counter
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi

st.set_page_config(page_title="YouTube Transcript Fetcher", page_icon="📝", layout="wide")

# ---------------- Session State Init ----------------
if "recent_videos" not in st.session_state:
    st.session_state["recent_videos"] = []
if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False
if "seek_time" not in st.session_state:
    st.session_state["seek_time"] = {}

# ---------------- Theme + Scrollable Tabs CSS ----------------
def apply_theme():
    dark_css = """
        .stApp { background-color: #0e1117; color: #f0f0f0; }
        .stTextInput input, .stTextArea textarea { background-color: #1e222a; color: #f0f0f0; }
        mark { background-color: #ffd54f; color: #000; }
    """ if st.session_state["dark_mode"] else """
        mark { background-color: #fff59d; }
    """
    st.markdown(f"""
    <style>
        {dark_css}
        /* Scrollable tab bar for many tabs */
        div[data-baseweb="tab-list"] {{
            overflow-x: auto;
            flex-wrap: nowrap !important;
            scrollbar-width: thin;
        }}
        div[data-baseweb="tab-list"] button {{
            white-space: nowrap;
        }}
    </style>
    """, unsafe_allow_html=True)

apply_theme()

# ---------------- Helper Functions ----------------
def sec_to_srt_time(seconds):
    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def sec_to_vtt_time(seconds):
    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def sec_to_mmss(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def build_srt(snippets):
    out = []
    for i, sn in enumerate(snippets, start=1):
        end = sn.start + sn.duration
        out.append(f"{i}\n{sec_to_srt_time(sn.start)} --> {sec_to_srt_time(end)}\n{sn.text}\n")
    return "\n".join(out)

def build_vtt(snippets):
    out = ["WEBVTT\n"]
    for sn in snippets:
        end = sn.start + sn.duration
        out.append(f"{sec_to_vtt_time(sn.start)} --> {sec_to_vtt_time(end)}\n{sn.text}\n")
    return "\n".join(out)

def fetch_transcript_with_fallback(video_id, language):
    ytt_api = YouTubeTranscriptApi()
    try:
        t = ytt_api.fetch(video_id, languages=[language])
        return t, language, True
    except Exception:
        t = ytt_api.fetch(video_id)
        return t, t.language_code, False

def get_available_languages(video_id):
    ytt_api = YouTubeTranscriptApi()
    listing = ytt_api.list(video_id)
    langs = []
    for tr in listing:
        langs.append({
            "code": tr.language_code,
            "label": f"{tr.language} ({tr.language_code}){' [auto]' if tr.is_generated else ''}",
            "is_generated": tr.is_generated
        })
    return langs

def word_stats(snippets):
    all_text = " ".join(sn.text for sn in snippets)
    words = re.findall(r"\w+", all_text, flags=re.UNICODE)
    total_duration = snippets[-1].start + snippets[-1].duration if snippets else 0
    reading_time_min = round(len(words) / 200, 1)
    return len(words), total_duration, reading_time_min, words

def highlight_html(text, term):
    if not term:
        return text
    pattern = re.escape(term)
    return re.sub(f"({pattern})", r"<mark>\1</mark>", text, flags=re.IGNORECASE)

def add_to_recent(video_id, language):
    entry = {"video_id": video_id, "language": language, "time": datetime.now().strftime("%H:%M:%S")}
    st.session_state["recent_videos"] = [e for e in st.session_state["recent_videos"] if e["video_id"] != video_id]
    st.session_state["recent_videos"].insert(0, entry)
    st.session_state["recent_videos"] = st.session_state["recent_videos"][:8]

def build_dataframe(snippets):
    return pd.DataFrame([{"Start (s)": round(sn.start, 2), "Duration (s)": round(sn.duration, 2), "Text": sn.text} for sn in snippets])

# ---------------- Shared Renderer (used by Single + Batch) ----------------
def render_video_panel(video_id, snippets, language, key_prefix):
    """Renders full detail panel (stats, player, search, subtabs, export) for one video."""
    lines = [f"[{sn.start:.2f}] {sn.text}" for sn in snippets]
    transcript_text = "\n".join(lines)
    df = build_dataframe(snippets)
    word_count, total_dur, read_min, all_words = word_stats(snippets)

    # Stats
    st.markdown("#### 📊 Stats")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Words", word_count)
    c2.metric("Duration", sec_to_mmss(total_dur))
    c3.metric("Reading Time", f"{read_min} min")
    c4.metric("Total Lines", len(snippets))

    # Video embed
    st.markdown("#### 🎬 Video")
    seek = st.session_state["seek_time"].get(key_prefix, 0)
    st.video(f"https://www.youtube.com/watch?v={video_id}", start_time=int(seek))

    # Search
    st.markdown("#### 🔎 Search")
    search_term = st.text_input("Search keyword", key=f"{key_prefix}_search")

    tab1, tab2, tab3, tab4 = st.tabs(["📄 Text", "📊 Table", "📈 Word Frequency", "⬇️ Export"])

    with tab1:
        filtered = snippets
        if search_term:
            filtered = [sn for sn in snippets if search_term.lower() in sn.text.lower()]
            st.caption(f"{len(filtered)} matching lines found")
        for sn in filtered:
            col_a, col_b = st.columns([1, 8])
            with col_a:
                if st.button(f"▶ {sec_to_mmss(sn.start)}", key=f"{key_prefix}_jump_{sn.start}"):
                    st.session_state["seek_time"][key_prefix] = sn.start
                    st.rerun()
            with col_b:
                st.markdown(highlight_html(sn.text, search_term), unsafe_allow_html=True)

    with tab2:
        display_df = df
        if search_term:
            display_df = df[df["Text"].str.contains(search_term, case=False, na=False)]
        st.dataframe(display_df, use_container_width=True, height=400)

    with tab3:
        st.caption("Sabse zyada repeat hone wale words (top 20)")
        word_freq = Counter(w.lower() for w in all_words if len(w) > 1)
        top_words = word_freq.most_common(20)
        freq_df = pd.DataFrame(top_words, columns=["Word", "Count"])
        if not freq_df.empty:
            st.bar_chart(freq_df.set_index("Word"))
            st.dataframe(freq_df, use_container_width=True)
        else:
            st.info("Not enough data for frequency chart.")

    with tab4:
        st.caption("Copy to clipboard (use the copy icon on the code block)")
        st.code(transcript_text, language=None)
        colx, coly = st.columns(2)
        with colx:
            st.download_button("⬇️ TXT", transcript_text, file_name=f"{video_id}_transcript.txt", mime="text/plain", key=f"{key_prefix}_dl_txt")
            st.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8"), file_name=f"{video_id}_transcript.csv", mime="text/csv", key=f"{key_prefix}_dl_csv")
        with coly:
            st.download_button("⬇️ SRT", build_srt(snippets), file_name=f"{video_id}.srt", mime="text/plain", key=f"{key_prefix}_dl_srt")
            st.download_button("⬇️ VTT", build_vtt(snippets), file_name=f"{video_id}.vtt", mime="text/plain", key=f"{key_prefix}_dl_vtt")

    return transcript_text, df, snippets

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("⚙️ Settings")
    st.session_state["dark_mode"] = st.toggle("🌙 Dark Mode", value=st.session_state["dark_mode"])
    apply_theme()

    st.markdown("---")
    st.header("🕓 Recent Videos")
    if st.session_state["recent_videos"]:
        for e in st.session_state["recent_videos"]:
            if st.button(f"{e['video_id']} ({e['language']}) - {e['time']}", key=f"recent_{e['video_id']}"):
                st.session_state["reload_video_id"] = e["video_id"]
                st.session_state["reload_language"] = e["language"]
    else:
        st.caption("Koi recent search nahi hai abhi.")

# ---------------- Main ----------------
st.title("📝 YouTube Transcript Fetcher")

mode = st.radio("Mode", ["Single Video", "Batch Mode"], horizontal=True)

# ============================================================
# SINGLE VIDEO MODE
# ============================================================
if mode == "Single Video":
    default_vid = st.session_state.pop("reload_video_id", "")
    video_id = st.text_input("Enter Video ID", value=default_vid).strip()

    lang_mode = st.radio("Language Selection", ["Auto-detect available languages", "Type language code manually"], horizontal=True)

    selected_language = None
    if lang_mode == "Auto-detect available languages" and video_id:
        if st.button("🔍 Fetch Available Languages"):
            try:
                st.session_state["lang_options"] = get_available_languages(video_id)
            except Exception as e:
                st.error(f"Error fetching languages: {e}")
                st.session_state["lang_options"] = []

        if "lang_options" in st.session_state and st.session_state["lang_options"]:
            options = st.session_state["lang_options"]
            labels = [o["label"] for o in options]
            picked = st.selectbox("Choose Language", labels)
            selected_language = options[labels.index(picked)]["code"]
    else:
        selected_language = st.text_input("Language Code (en, ur, hi)", value="en").strip()

    if st.button("📥 Fetch Transcript", type="primary"):
        if not video_id:
            st.warning("Pehle Video ID daalo.")
        elif not selected_language:
            st.warning("Language select ya type karo.")
        else:
            try:
                transcript, used_lang, matched = fetch_transcript_with_fallback(video_id, selected_language)
                if matched:
                    st.success(f"Transcript fetched in '{used_lang}'")
                else:
                    st.warning(f"'{selected_language}' not found. Fetched default: '{used_lang}'")

                st.session_state["transcript_obj"] = list(transcript)
                st.session_state["current_video_id"] = video_id
                st.session_state["current_language"] = used_lang
                add_to_recent(video_id, used_lang)
            except Exception as e:
                st.error(f"Error: {e}")
                st.session_state.pop("transcript_obj", None)

    if "transcript_obj" in st.session_state and st.session_state.get("current_video_id") == video_id:
        render_video_panel(video_id, st.session_state["transcript_obj"], st.session_state["current_language"], key_prefix="single")

# ============================================================
# BATCH MODE
# ============================================================
else:
    st.markdown("Multiple Video IDs daalo — **ek line mein ek ID**")
    batch_ids_raw = st.text_area("Video IDs", height=150, placeholder="uQFLY8rQVYA\ndQw4w9WgXcQ\n...")
    batch_language = st.text_input("Language Code (fallback to default if not found)", value="en").strip()

    if st.button("📥 Fetch All Transcripts", type="primary"):
        video_ids = [v.strip() for v in batch_ids_raw.splitlines() if v.strip()]
        if not video_ids:
            st.warning("Kam se kam ek Video ID daalo.")
        else:
            batch_data = {}
            statuses = []
            progress = st.progress(0, text="Starting...")

            for i, vid in enumerate(video_ids):
                progress.progress(i / len(video_ids), text=f"Fetching {vid} ({i+1}/{len(video_ids)})")
                try:
                    transcript, used_lang, matched = fetch_transcript_with_fallback(vid, batch_language)
                    snippets = list(transcript)
                    batch_data[vid] = {"snippets": snippets, "language": used_lang}
                    statuses.append({"Video ID": vid, "Status": "✅ Success", "Language": used_lang, "Lines": len(snippets)})
                except Exception as e:
                    statuses.append({"Video ID": vid, "Status": f"❌ Failed: {e}", "Language": "-", "Lines": 0})

            progress.progress(1.0, text="Done!")
            st.session_state["batch_data"] = batch_data
            st.session_state["batch_statuses"] = statuses

    # ---------- Display batch results as per-video tabs ----------
    if "batch_data" in st.session_state and st.session_state["batch_data"]:
        batch_data = st.session_state["batch_data"]
        statuses_df = pd.DataFrame(st.session_state["batch_statuses"])

        success_count = (statuses_df["Status"] == "✅ Success").sum()
        st.caption(f"{success_count}/{len(statuses_df)} transcripts fetched successfully")
        with st.expander("📋 Fetch Status Summary"):
            st.dataframe(statuses_df, use_container_width=True)

        video_ids_ok = list(batch_data.keys())
        tab_labels = [f"🎬 {vid}" for vid in video_ids_ok] + ["⬇️ Download All"]
        tabs = st.tabs(tab_labels)

        # One tab per video — full detail panel each
        for idx, vid in enumerate(video_ids_ok):
            with tabs[idx]:
                st.markdown(f"### Video: `{vid}`")
                render_video_panel(vid, batch_data[vid]["snippets"], batch_data[vid]["language"], key_prefix=f"batch_{vid}")

        # Final tab — download everything together
        with tabs[-1]:
            st.markdown("### 📦 Download Everything")
            st.caption(f"{len(video_ids_ok)} videos ka TXT + CSV + SRT ek ZIP mein.")

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for vid in video_ids_ok:
                    snippets = batch_data[vid]["snippets"]
                    txt_content = "\n".join(f"[{sn.start:.2f}] {sn.text}" for sn in snippets)
                    csv_content = build_dataframe(snippets).to_csv(index=False)
                    zf.writestr(f"{vid}_transcript.txt", txt_content)
                    zf.writestr(f"{vid}_transcript.csv", csv_content)
                    zf.writestr(f"{vid}.srt", build_srt(snippets))

            st.download_button(
                "⬇️ Download All (ZIP: TXT + CSV + SRT for every video)",
                data=zip_buffer.getvalue(),
                file_name="transcripts_batch.zip",
                mime="application/zip",
                type="primary"
            )