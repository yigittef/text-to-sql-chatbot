"""Tüm iş mantığı nlq_service.NaturalLanguageQueryService içinde yer alır."""
import logging
import os
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from config import ConfigurationError, DatabaseConfig, LocalLLMConfig, LLMConfig
from db_repository import DatabaseRepository
from export_service import dataframe_to_excel_bytes, dataframe_to_pdf_bytes
from favorites_repository import FavoritesRepository
from llm_client import GeminiLLMClient, LocalLLMClient
from logging_llm_client import LoggingLLMClient
from models import ChatEntry
from nlq_service import NaturalLanguageQueryService
from profile_repository import ProfileRepository
from schema_introspector import SchemaIntrospector

load_dotenv()

# NOT: Log dosyasının yolu artık SABİT (app.py'nin bulunduğu klasöre göre
# mutlak yol) — önceden "llm_test_log.txt" göreli bir yoldu, yani terminal
# hangi klasörden açılırsa açılsın (git komutlarından sonra farklı bir
# klasörden başlatılmış olabilir) dosya O AN çalışılan klasörde oluşuyordu,
# insan onu ChatBotSon klasöründe arayınca bulamıyordu. Artık nereden
# çalıştırılırsa çalıştırılsın hep aynı, tahmin edilebilir yere yazılıyor.
_LOG_DOSYA_YOLU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_test_log.txt")

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DOSYA_YOLU, encoding="utf-8"),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_BOT_AVATAR = "🤖"

LLM_PROVIDER_GEMINI = "gemini"
LLM_PROVIDER_LOCAL = "local"
_LLM_PROVIDER_LABELS = {
    LLM_PROVIDER_GEMINI: "Gemini API",
    LLM_PROVIDER_LOCAL: "Yerel Model (Ollama, VPN gerekebilir)",
}
_PROVIDER_AVATARS = {
    LLM_PROVIDER_GEMINI: "✨",
    LLM_PROVIDER_LOCAL: "🤖",
}
_PROVIDER_BADGES = {
    LLM_PROVIDER_GEMINI: "🔵 **Gemini API**",
    LLM_PROVIDER_LOCAL: "🟢 **Yerel Model**",
}

st.set_page_config(page_title="NLQ Chatbot", page_icon="💬", layout="wide")

st.markdown("""
<style>
#MainMenu, header, footer {visibility: hidden;}
.block-container {padding: 0 !important;}

.st-key-widget_bubble button {
    position: fixed !important;
    bottom: 24px !important;
    right: 24px !important;
    width: 56px !important;
    height: 56px !important;
    min-width: 56px !important;
    border-radius: 50% !important;
    font-size: 22px !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35) !important;
    z-index: 9999 !important;
}

.st-key-widget_panel {
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 300px;
    height: 460px;
    background: #17181c !important;
    border-radius: 16px !important;
    box-shadow: 0 10px 36px rgba(0,0,0,0.45) !important;
    z-index: 9999 !important;
    padding: 14px 16px !important;
    overflow: auto !important;
    border: 1px solid #2a2b30 !important;
}

.st-key-widget_header { cursor: move; }

.st-key-widget_panel h3 {
    font-size: 15px !important;
    text-align: center;
    margin: 4px 0 8px 0 !important;
}
.st-key-widget_panel .stCaption, .st-key-widget_panel [data-testid="stCaptionContainer"] {
    font-size: 10px !important;
    text-align: center;
}
.st-key-widget_panel [data-testid="stChatMessageContent"] p,
.st-key-widget_panel [data-testid="stChatMessageContent"] li {
    font-size: 12px !important;
    line-height: 1.45 !important;
}
.st-key-widget_panel [data-testid="stChatInput"] textarea {
    font-size: 12px !important;
}
.st-key-widget_panel [data-baseweb="avatar"] {
    width: 24px !important;
    height: 24px !important;
    font-size: 13px !important;
}
.st-key-widget_panel [data-testid="stRadio"] label {
    font-size: 11px !important;
}
.widget-robot-avatar {
    font-size: 30px;
    text-align: center;
    line-height: 1;
    margin-bottom: 4px;
}

.st-key-widget_panel_full {
    max-width: 720px;
    margin: 40px auto;
    padding: 0 16px;
}
.st-key-widget_panel_full h3 {
    text-align: center;
    font-size: 24px !important;
}
.st-key-widget_panel_full .stCaption {
    text-align: center;
    font-size: 14px !important;
}
.st-key-widget_panel_full [data-testid="stChatMessageContent"] p,
.st-key-widget_panel_full [data-testid="stChatMessageContent"] li {
    font-size: 16px !important;
    line-height: 1.55 !important;
}
.st-key-widget_panel_full [data-testid="stChatInput"] textarea {
    font-size: 15px !important;
}
.widget-robot-avatar-full {
    font-size: 52px;
    text-align: center;
    line-height: 1;
    margin-bottom: 8px;
}

.st-key-widget_close button, .st-key-widget_expand button {
    border-radius: 50% !important;
    width: 28px !important;
    height: 28px !important;
    min-width: 28px !important;
    padding: 0 !important;
}

.st-key-examples_container {
    max-width: 92%;
    margin: 0 auto 6px auto;
}
.st-key-examples_container div[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
    overflow-x: visible !important;
    gap: 5px !important;
    justify-content: center !important;
    padding-bottom: 0 !important;
}
.st-key-examples_container div[data-testid="stHorizontalBlock"] > div {
    flex: 0 1 auto !important;
    min-width: 0 !important;
    width: auto !important;
}
.st-key-widget_panel .st-key-examples_container button {
    font-size: 10px !important;
    padding: 3px 9px !important;
    white-space: nowrap !important;
    max-width: 120px !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    display: inline-block !important;
}
.st-key-widget_panel_full .st-key-examples_container button {
    font-size: 13px !important;
    padding: 6px 14px !important;
    max-width: 200px !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    display: inline-block !important;
}
.st-key-examples_container p {
    text-align: center !important;
    font-size: 10px !important;
    margin-bottom: 3px !important;
    opacity: 0.75;
}
</style>
""", unsafe_allow_html=True)


_DRAG_RESIZE_SCRIPT = """
<script>
(function() {
    const doc = window.parent.document;
    function getPanel() { return doc.querySelector('.st-key-widget_panel'); }

    const EDGES = [
        {cls:'k-tl', cursor:'nwse-resize', top:true,  left:true,  w:true,  h:true},
        {cls:'k-tr', cursor:'nesw-resize', top:true,  left:false, w:true,  h:true},
        {cls:'k-bl', cursor:'nesw-resize', top:false, left:true,  w:true,  h:true},
        {cls:'k-br', cursor:'nwse-resize', top:false, left:false, w:true,  h:true},
        {cls:'k-t',  cursor:'ns-resize',   top:true,  left:false, w:false, h:true},
        {cls:'k-b',  cursor:'ns-resize',   top:false, left:false, w:false, h:true},
        {cls:'k-l',  cursor:'ew-resize',   top:false, left:true,  w:true,  h:false},
        {cls:'k-r',  cursor:'ew-resize',   top:false, left:false, w:true,  h:false},
    ];

    function place(h, r, spec) {
        const t = 10;
        if (spec.cls === 'k-tl') { h.style.left = (r.left-t/2)+'px'; h.style.top = (r.top-t/2)+'px'; }
        if (spec.cls === 'k-tr') { h.style.left = (r.right-t/2)+'px'; h.style.top = (r.top-t/2)+'px'; }
        if (spec.cls === 'k-bl') { h.style.left = (r.left-t/2)+'px'; h.style.top = (r.bottom-t/2)+'px'; }
        if (spec.cls === 'k-br') { h.style.left = (r.right-t/2)+'px'; h.style.top = (r.bottom-t/2)+'px'; }
        if (spec.cls === 'k-t')  { h.style.left = (r.left+r.width/2-20)+'px'; h.style.top = (r.top-t/2)+'px'; h.style.width='40px'; }
        if (spec.cls === 'k-b')  { h.style.left = (r.left+r.width/2-20)+'px'; h.style.top = (r.bottom-t/2)+'px'; h.style.width='40px'; }
        if (spec.cls === 'k-l')  { h.style.left = (r.left-t/2)+'px'; h.style.top = (r.top+r.height/2-20)+'px'; h.style.height='40px'; }
        if (spec.cls === 'k-r')  { h.style.left = (r.right-t/2)+'px'; h.style.top = (r.top+r.height/2-20)+'px'; h.style.height='40px'; }
    }

    function positionHandles() {
        const panel = getPanel();
        if (!panel) return;
        const r = panel.getBoundingClientRect();
        EDGES.forEach(spec => {
            const h = doc.querySelector('.widget-h.' + spec.cls);
            if (h) place(h, r, spec);
        });
    }

    function createHandlesOnce() {
        if (doc.querySelector('.widget-h.k-br')) { positionHandles(); return; }
        EDGES.forEach(spec => {
            const h = doc.createElement('div');
            h.className = 'widget-h ' + spec.cls;
            h.style.position = 'fixed';
            h.style.width = '10px';
            h.style.height = '10px';
            h.style.background = 'rgba(255,255,255,0.25)';
            h.style.borderRadius = '4px';
            h.style.cursor = spec.cursor;
            h.style.zIndex = 10001;
            doc.body.appendChild(h);
            h.addEventListener('mousedown', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const panel = getPanel();
                if (!panel) return;
                const start = panel.getBoundingClientRect();
                const sx = e.clientX, sy = e.clientY;
                function onMove(ev) {
                    const dx = ev.clientX - sx, dy = ev.clientY - sy;
                    let left = start.left, top = start.top, width = start.width, height = start.height;
                    if (spec.w) { if (spec.left) { width = start.width - dx; left = start.left + dx; } else { width = start.width + dx; } }
                    if (spec.h) { if (spec.top) { height = start.height - dy; top = start.top + dy; } else { height = start.height + dy; } }
                    width = Math.max(280, width);
                    height = Math.max(340, height);
                    panel.style.left = left + 'px';
                    panel.style.top = top + 'px';
                    panel.style.right = 'auto';
                    panel.style.bottom = 'auto';
                    panel.style.width = width + 'px';
                    panel.style.height = height + 'px';
                    positionHandles();
                }
                function onUp() {
                    doc.removeEventListener('mousemove', onMove);
                    doc.removeEventListener('mouseup', onUp);
                }
                doc.addEventListener('mousemove', onMove);
                doc.addEventListener('mouseup', onUp);
            });
        });
        positionHandles();
    }

    if (!window.__widgetDragBound) {
        window.__widgetDragBound = true;
        doc.addEventListener('mousedown', function(e) {
            const header = e.target.closest('.st-key-widget_header');
            if (!header) return;
            if (e.target.closest('button')) return;
            const panel = getPanel();
            if (!panel) return;
            e.preventDefault();
            const start = panel.getBoundingClientRect();
            const sx = e.clientX, sy = e.clientY;
            function onMove(ev) {
                panel.style.left = (start.left + ev.clientX - sx) + 'px';
                panel.style.top = (start.top + ev.clientY - sy) + 'px';
                panel.style.right = 'auto';
                panel.style.bottom = 'auto';
                positionHandles();
            }
            function onUp() {
                doc.removeEventListener('mousemove', onMove);
                doc.removeEventListener('mouseup', onUp);
            }
            doc.addEventListener('mousemove', onMove);
            doc.addEventListener('mouseup', onUp);
        });
    }

    function init() {
        const panel = getPanel();
        if (!panel) {
            doc.querySelectorAll('.widget-h').forEach(el => el.remove());
            return;
        }
        createHandlesOnce();
    }

    if (window.__widgetInterval) clearInterval(window.__widgetInterval);
    window.__widgetInterval = setInterval(init, 400);
    init();
})();
</script>
"""


def _time_based_greeting() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Günaydın! ☀️"
    if 12 <= hour < 18:
        return "Merhaba! 👋"
    if 18 <= hour < 22:
        return "İyi akşamlar! 🌆"
    return "İyi geceler! 🌙"


@st.cache_resource
def get_db_repository() -> DatabaseRepository:
    return DatabaseRepository(DatabaseConfig.from_env())


@st.cache_resource
def get_llm_client(provider: str) -> LoggingLLMClient:
    if provider == LLM_PROVIDER_GEMINI:
        real_client = GeminiLLMClient(LLMConfig.from_env())
    else:
        real_client = LocalLLMClient(LocalLLMConfig.from_env())
    return LoggingLLMClient(real_client)


@st.cache_resource
def get_schema_introspector(_db_repository: DatabaseRepository) -> SchemaIntrospector:
    return SchemaIntrospector(_db_repository.engine)


@st.cache_resource
def get_favorites_repository() -> FavoritesRepository:
    return FavoritesRepository(max_examples=3)


@st.cache_resource
def get_profile_repository() -> ProfileRepository:
    return ProfileRepository(get_db_repository())


def get_service(provider: str) -> NaturalLanguageQueryService:
    db_repository = get_db_repository()
    return NaturalLanguageQueryService(
        llm_client=get_llm_client(provider),
        db_repository=db_repository,
        schema_introspector=get_schema_introspector(db_repository),
        profile_repository=get_profile_repository(),
    )


def _entry_dataframe(entry: ChatEntry):
    if entry.query_result is None:
        return None
    return pd.DataFrame.from_records(entry.query_result.rows, columns=list(entry.query_result.columns))


def _chart_is_meaningful(df: pd.DataFrame) -> bool:
    if df is None or df.empty or len(df.columns) < 2 or len(df) < 2:
        return False
    other_columns = df.columns[1:]
    return any(pd.api.types.is_numeric_dtype(df[c]) for c in other_columns)


def _render_chart(df: pd.DataFrame) -> None:
    label_column = df.columns[0]
    numeric_columns = [c for c in df.columns if c != label_column and pd.api.types.is_numeric_dtype(df[c])]
    if numeric_columns:
        st.bar_chart(df.set_index(label_column)[numeric_columns])


def _toggle(index_set: set, idx: int) -> None:
    if idx in index_set:
        index_set.discard(idx)
    else:
        index_set.add(idx)


def render_examples():
    examples, title = get_favorites_repository().get_examples()
    selected = None
    with st.container(key="examples_container"):
        st.write(f"**{title}:**")
        columns = st.columns(len(examples))
        for column, example in zip(columns, examples):
            if column.button(example, key=f"ex_{example}", help=example):
                selected = example
    return selected


def handle_new_question(question: str) -> None:
    get_favorites_repository().record_question(question)
    provider = st.session_state.get("llm_provider", LLM_PROVIDER_GEMINI)
    with st.spinner("Düşünüyor..."):
        try:
            service = get_service(provider)
            entry = service.answer(question, history=st.session_state.chat_history)
        except ConfigurationError:
            logger.error("Yapılandırma hatası.", exc_info=True)
            entry = ChatEntry(
                question=question,
                error_message="Uygulama yapılandırması eksik. Lütfen yönetici ile iletişime geçin.",
            )
        except Exception:
            logger.exception("Soru işlenirken beklenmeyen bir hata oluştu.")
            entry = ChatEntry(
                question=question,
                error_message="Sorunuz işlenirken bir hata oluştu. Lütfen farklı bir şekilde tekrar deneyin.",
            )
    entry.llm_provider = provider
    st.session_state.chat_history.append(entry)


def _render_profile(entry: ChatEntry) -> None:
    if entry.profile is not None:
        _render_customer_profile(entry.profile)
    if entry.employee_profile is not None:
        _render_employee_profile(entry.employee_profile)


def _render_customer_profile(profile) -> None:
    customer = profile.customer_row
    with st.expander(f"📇 {customer[1]} — Müşteri Profili", expanded=True):
        st.write(f"**Şehir:** {customer[2]} | **Telefon:** {customer[3]} | **Kayıt:** {customer[4]}")
        st.write(f"**Toplam Sipariş:** {len(profile.orders)}")
        if profile.orders:
            orders_df = pd.DataFrame.from_records(
                profile.orders, columns=["Sipariş ID", "Tarih", "Tutar", "Durum"]
            )
            st.dataframe(orders_df, use_container_width=True, hide_index=True)
        if profile.top_products:
            st.write("**En Çok Aldığı Ürünler:**")
            products_df = pd.DataFrame.from_records(profile.top_products, columns=["Ürün", "Toplam Adet"])
            st.dataframe(products_df, use_container_width=True, hide_index=True)
        if profile.account_card:
            st.write(f"**Cari Kart:** {profile.account_card[0]} — {profile.account_card[2]}")
        if profile.shipments:
            st.write("**Kargo Durumları:**")
            shipments_df = pd.DataFrame.from_records(
                profile.shipments, columns=["Sipariş ID", "Firma", "Durum", "Gönderim", "Teslim"]
            )
            st.dataframe(shipments_df, use_container_width=True, hide_index=True)


def _render_employee_profile(profile) -> None:
    employee = profile.employee_row
    with st.expander(f"🧑‍💼 {employee[1]} — Çalışan Profili", expanded=True):
        st.write(f"**Departman:** {employee[2]} | **Unvan:** {employee[3]}")
        st.write(f"**İşe Başlama:** {employee[4]} | **Şehir:** {employee[5]}")
        if profile.izin_talepleri:
            st.write("**İzin Talepleri:**")
            izin_df = pd.DataFrame.from_records(
                profile.izin_talepleri, columns=["Başlangıç", "Bitiş", "Tür", "Durum"]
            )
            st.dataframe(izin_df, use_container_width=True, hide_index=True)
        if profile.performans_kayitlari:
            st.write("**Performans Değerlendirmeleri:**")
            perf_df = pd.DataFrame.from_records(
                profile.performans_kayitlari, columns=["Tarih", "Puan", "Yorum"]
            )
            st.dataframe(perf_df, use_container_width=True, hide_index=True)
        if profile.tamamlanan_egitimler:
            st.write("**Tamamlanan Eğitimler:**")
            egitim_df = pd.DataFrame.from_records(
                profile.tamamlanan_egitimler, columns=["Eğitim", "Tarih", "Durum"]
            )
            st.dataframe(egitim_df, use_container_width=True, hide_index=True)


def render_greeting(fullscreen: bool) -> None:
    if st.session_state.chat_history:
        return
    avatar_class = "widget-robot-avatar-full" if fullscreen else "widget-robot-avatar"
    st.markdown(f'<div class="{avatar_class}">{_BOT_AVATAR}</div>', unsafe_allow_html=True)
    with st.chat_message("assistant", avatar=_BOT_AVATAR):
        st.write(f"{_time_based_greeting()} Ben NLQ Chatbot — size nasıl yardımcı olabilirim?")


def render_history() -> None:
    for idx, entry in enumerate(st.session_state.chat_history):
        with st.chat_message("user"):
            st.write(entry.question)

        avatar = _PROVIDER_AVATARS.get(entry.llm_provider, _BOT_AVATAR)
        with st.chat_message("assistant", avatar=avatar):
            if entry.llm_provider in _PROVIDER_BADGES:
                st.caption(_PROVIDER_BADGES[entry.llm_provider])

            if entry.has_error:
                st.error(entry.error_message)
                # NOT: Hata olsa bile, eğer bir SQL üretilmişse (ama
                # çalıştırılamamışsa) onu da gösterebiliyoruz - "hiçbir şey
                # sorgulanmadı" değil "sorgulandı ama hata verdi" ayrımı
                # artık görünür.
                if entry.generated_sql:
                    with st.popover("⋮"):
                        if st.button("🔍 SQL Sorgusunu Göster", key=f"sql_{idx}", use_container_width=True):
                            _toggle(st.session_state.show_sql, idx)
                            st.rerun()
                    if idx in st.session_state.show_sql:
                        st.code(entry.generated_sql, language="sql")
                continue

            st.write(entry.answer)
            _render_profile(entry)

            df = _entry_dataframe(entry)
            has_sql = bool(entry.generated_sql)
            has_data = df is not None and not df.empty

            if has_data:
                st.dataframe(df, use_container_width=True, hide_index=True)

            if has_sql or has_data:
                with st.popover("⋮"):
                    if has_sql and st.button("🔍 SQL Sorgusunu Göster", key=f"sql_{idx}", use_container_width=True):
                        _toggle(st.session_state.show_sql, idx)
                        st.rerun()
                    if has_data and _chart_is_meaningful(df):
                        if st.button("📊 Grafiği Göster/Gizle", key=f"chart_{idx}", use_container_width=True):
                            _toggle(st.session_state.show_chart, idx)
                            st.rerun()
                    if has_data:
                        st.download_button(
                            "📥 Excel'de İndir", data=dataframe_to_excel_bytes(df),
                            file_name=f"sonuc_{idx}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"excel_{idx}", use_container_width=True,
                        )
                        st.download_button(
                            "📄 PDF Olarak İndir", data=dataframe_to_pdf_bytes(df, entry.question),
                            file_name=f"rapor_{idx}.pdf", mime="application/pdf",
                            key=f"pdf_{idx}", use_container_width=True,
                        )

            if idx in st.session_state.show_sql and has_sql:
                st.code(entry.generated_sql, language="sql")
            if idx in st.session_state.show_chart and has_data and _chart_is_meaningful(df):
                _render_chart(df)


def render_widget_bubble() -> None:
    with st.container(key="widget_bubble"):
        if st.button("💬", key="open_widget_btn"):
            st.session_state.widget_open = True
            st.rerun()


def render_widget_panel() -> None:
    fullscreen = st.session_state.widget_fullscreen
    panel_key = "widget_panel_full" if fullscreen else "widget_panel"

    with st.container(key=panel_key):
        with st.container(key="widget_header"):
            header_col, expand_col, close_col = st.columns([6, 1, 1])
            header_col.markdown("### 🤖 NLQ Chatbot")

            with expand_col:
                st.container(key="widget_expand")
                expand_icon = "🗗" if fullscreen else "⛶"
                if st.button(expand_icon, key="expand_widget_btn", help="Tam ekran / normal boyut"):
                    st.session_state.widget_fullscreen = not fullscreen
                    st.rerun()

            with close_col:
                st.container(key="widget_close")
                if st.button("✕", key="close_widget_btn"):
                    st.session_state.widget_open = False
                    st.session_state.widget_fullscreen = False
                    st.rerun()

        st.caption("Veritabanına doğal dille soru sorun — yalnızca bilgi okunur")

        st.radio(
            "Kullanılacak model:",
            options=[LLM_PROVIDER_GEMINI, LLM_PROVIDER_LOCAL],
            format_func=lambda p: _LLM_PROVIDER_LABELS[p],
            horizontal=True,
            key="llm_provider",
            label_visibility="collapsed",
        )

        render_greeting(fullscreen)

        selected_example = render_examples()

        question = st.chat_input("Sorunuzu yazın...") or selected_example
        if question:
            handle_new_question(question)
            st.rerun()

        render_history()

        if st.session_state.chat_history and st.button("🗑️ Sohbeti Temizle", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.show_sql = set()
            st.session_state.show_chart = set()
            st.rerun()


def main() -> None:
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("show_sql", set())
    st.session_state.setdefault("show_chart", set())
    st.session_state.setdefault("widget_open", False)
    st.session_state.setdefault("widget_fullscreen", False)
    st.session_state.setdefault("llm_provider", LLM_PROVIDER_GEMINI)

    if st.session_state.widget_open:
        render_widget_panel()
    else:
        render_widget_bubble()

    components.html(_DRAG_RESIZE_SCRIPT, height=0)


if __name__ == "__main__":
    main()