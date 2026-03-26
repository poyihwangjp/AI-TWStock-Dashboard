import streamlit as st
from yahooquery import Ticker
import plotly.graph_objects as go
import pandas as pd
import google.generativeai as genai
import feedparser
import re
import time
from datetime import datetime, timedelta

# ==========================================
# 1. 網頁基本設定
# ==========================================
st.set_page_config(page_title="AI 台股分析儀表板", layout="wide")
st.title("📈 專屬 AI 台股分析儀表板")

# --- 新增：初始化網頁記憶體 (Session State) ---
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_ticker" not in st.session_state:
    st.session_state.last_ticker = ""

# ==========================================
# 2. 側邊欄設定 (Sidebar)
# ==========================================
st.sidebar.header("設定區")
st.sidebar.markdown("**💡 提示：上市請加 .TW (如 2330.TW)，上櫃加 .TWO (如 3293.TWO)**")
ticker_symbol = st.sidebar.text_input("請輸入台股代碼", value="2330.TW").upper()

# --- 新增：如果切換了股票，就自動清空前一檔股票的對話紀錄 ---
if ticker_symbol != st.session_state.last_ticker:
    st.session_state.chat_history = []
    st.session_state.last_ticker = ticker_symbol

company_name = st.sidebar.text_input("請輸入公司簡稱 (用於精準抓取新聞)", value="台積電")
time_period = st.sidebar.selectbox("選擇 K 線圖時間範圍", ["1mo", "3mo", "6mo", "1y", "ytd"])

# --- 圖表顯示開關 ---
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 圖表顯示開關")
show_bb = st.sidebar.checkbox("顯示布林通道 (Bollinger Bands)", value=True)
show_fib = st.sidebar.checkbox("顯示黃金分割線 (Fibonacci)", value=True)

api_key = st.sidebar.text_input("請輸入 Gemini API Key (選填)", type="password", value="")

st.sidebar.markdown("---")
st.sidebar.subheader("🔒 獨家付費情報")
st.sidebar.write("可直接貼上文字，或將大叔的文章存成 PDF 上傳")
kol_text = st.sidebar.text_area("請貼上文字段落 (選填)", height=100)
kol_pdf = st.sidebar.file_uploader("📄 匯入完整文章 (PDF)", type=['pdf'])

if kol_pdf:
    st.sidebar.success("✅ PDF 檔案已載入，準備交由 AI 研讀！")

st.sidebar.markdown("---")
st.sidebar.subheader("🌐 社群與論壇動態追蹤 (RSS)")
rss_url = st.sidebar.text_input("KOL 追蹤 (如財報狗 FB)", value="")
ceo_rss_url = st.sidebar.text_input("市場情緒與重訊 (如 PTT/Google快訊)", value="")

# ==========================================
# 3. 獲取市場數據 (yahooquery 完美相容版)
# ==========================================
@st.cache_data(ttl=3600)
def load_data(ticker_symbol, period):
    t = Ticker(ticker_symbol)
    
    hist = t.history(period=period)
    if isinstance(hist, pd.DataFrame) and not hist.empty:
        hist = hist.reset_index()
        if 'date' in hist.columns:
            hist = hist.set_index('date')
        hist.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
    else:
        hist = pd.DataFrame()

    info = {}
    try:
        stats_raw = t.key_stats
        details_raw = t.summary_detail
        
        stats = stats_raw.get(ticker_symbol, {}) if isinstance(stats_raw, dict) else {}
        details = details_raw.get(ticker_symbol, {}) if isinstance(details_raw, dict) else {}
        
        if not stats and isinstance(stats_raw, dict) and len(stats_raw) > 0:
            stats = list(stats_raw.values())[0]
        if not details and isinstance(details_raw, dict) and len(details_raw) > 0:
            details = list(details_raw.values())[0]
            
        if isinstance(stats, dict) and isinstance(details, dict):
            info = {
                'marketCap': details.get('marketCap', 0),
                'fiftyTwoWeekHigh': details.get('fiftyTwoWeekHigh', 'N/A'),
                'fiftyTwoWeekLow': details.get('fiftyTwoWeekLow', 'N/A'),
                'heldPercentInsiders': stats.get('heldPercentInsiders', 0),
                'heldPercentInstitutions': stats.get('heldPercentInstitutions', 0),
                'shortPercentOfFloat': stats.get('shortPercentOfFloat', 0),
                'shortRatio': stats.get('shortRatio', 'N/A')
            }
    except Exception:
        pass

    news_list = []
    try:
        raw_news = t.news()
        if isinstance(raw_news, dict):
            news_list = raw_news.get(ticker_symbol, [])
            if not news_list and len(raw_news) > 0:
                news_list = list(raw_news.values())[0]
        elif isinstance(raw_news, list):
            news_list = raw_news
    except Exception:
        pass

    return hist, info, news_list

st.write(f"正在載入 **{ticker_symbol}** 的即時數據...")
hist_data, stock_info, stock_news = load_data(ticker_symbol, time_period)

if hist_data.empty:
    st.error("找不到該股票的數據，請確認代碼是否正確 (記得加上 .TW 或 .TWO)。")
else:
    # 過濾掉尚未收盤的空值
    hist_data = hist_data.dropna(subset=['Close'])

    # ==========================================
    # 4. 頂部數據看板 (台幣計價版)
    # ==========================================
    col1, col2, col3, col4 = st.columns(4)
    current_price = hist_data['Close'].iloc[-1]
    prev_price = hist_data['Close'].iloc[-2]
    price_change = current_price - prev_price
    pct_change = (price_change / prev_price) * 100

    col1.metric("目前股價", f"NT$ {current_price:.2f}", f"{price_change:.2f} ({pct_change:.2f}%)")
    market_cap_billions = stock_info.get('marketCap', 0) / 1e8
    col2.metric("市值", f"NT$ {market_cap_billions:.2f} 億" if market_cap_billions > 0 else "N/A")
    col3.metric("52週最高", f"NT$ {stock_info.get('fiftyTwoWeekHigh', 'N/A')}")
    col4.metric("52週最低", f"NT$ {stock_info.get('fiftyTwoWeekLow', 'N/A')}")

    st.markdown("---")

    # ==========================================
    # 5. 籌碼結構與做空數據
    # ==========================================
    st.markdown("### 🕵️‍♂️ 籌碼結構與做空數據 (註：Yahoo 針對台股通常無籌碼資料)")
    chip_col1, chip_col2, chip_col3, chip_col4 = st.columns(4)

    insider_pct = stock_info.get('heldPercentInsiders', 0) * 100
    inst_pct = stock_info.get('heldPercentInstitutions', 0) * 100
    short_pct = stock_info.get('shortPercentOfFloat', 0) * 100
    short_ratio = stock_info.get('shortRatio', 'N/A')

    chip_col1.metric("內部人持股比例", f"{insider_pct:.2f}%" if insider_pct else "N/A", help="公司高層與大股東持有的比例")
    chip_col2.metric("機構持股比例", f"{inst_pct:.2f}%" if inst_pct else "N/A", help="外資、投信等法人的總持股比例")
    chip_col3.metric("空單佔流通股比例", f"{short_pct:.2f}%" if short_pct else "N/A", help="融券與借券賣出佔比")
    chip_col4.metric("空單回補天數 (Days to Cover)", f"{short_ratio}", help="空軍需要多少天的交易量才能買回所有空單")

    st.markdown("---")

    # ==========================================
    # 6. 技術面視覺化：全配版技術指標圖表 (含成交量)
    # ==========================================
    st.subheader(f"📊 {ticker_symbol} 技術面走勢 ({time_period})")
    from plotly.subplots import make_subplots
    
    hist_data['MA20'] = hist_data['Close'].rolling(window=20).mean()
    hist_data['STD20'] = hist_data['Close'].rolling(window=20).std()
    hist_data['Upper_Band'] = hist_data['MA20'] + (hist_data['STD20'] * 2) 
    hist_data['Lower_Band'] = hist_data['MA20'] - (hist_data['STD20'] * 2) 
    
    period_high = hist_data['High'].max()
    period_low = hist_data['Low'].min()
    diff = period_high - period_low
    fib_levels = {
        '0.0%': period_high, '23.6%': period_high - 0.236 * diff, '38.2%': period_high - 0.382 * diff,
        '50.0%': period_high - 0.500 * diff, '61.8%': period_high - 0.618 * diff, '100.0%': period_low
    }

    exp1 = hist_data['Close'].ewm(span=12, adjust=False).mean()
    exp2 = hist_data['Close'].ewm(span=26, adjust=False).mean()
    hist_data['MACD'] = exp1 - exp2
    hist_data['Signal'] = hist_data['MACD'].ewm(span=9, adjust=False).mean()
    hist_data['Histogram'] = hist_data['MACD'] - hist_data['Signal']
    
    delta = hist_data['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    hist_data['RSI'] = 100 - (100 / (1 + rs))

    vol_colors = ['red' if close >= open else 'green' for close, open in zip(hist_data['Close'], hist_data['Open'])] 

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.45, 0.15, 0.2, 0.2])

    fig.add_trace(go.Candlestick(x=hist_data.index, open=hist_data['Open'], high=hist_data['High'], low=hist_data['Low'], close=hist_data['Close'], name="K線", increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
    
    if show_bb:
        fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Upper_Band'], mode='lines', name='布林上軌', line=dict(color='rgba(173, 216, 230, 0.5)', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Lower_Band'], mode='lines', name='布林下軌', line=dict(color='rgba(173, 216, 230, 0.5)', width=1), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.1)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['MA20'], mode='lines', name='20日均線', line=dict(color='orange', width=2)), row=1, col=1)

    if show_fib:
        fib_colors = ['red', 'orange', 'yellow', 'green', 'blue', 'purple']
        for (level_name, price), color in zip(fib_levels.items(), fib_colors):
            fig.add_hline(y=price, line_dash="dot", line_color=color, opacity=0.5, row=1, col=1, annotation_text=f"Fib {level_name} (${price:.2f})", annotation_position="right")

    fig.add_trace(go.Bar(x=hist_data.index, y=hist_data['Volume'], name='成交量', marker_color=vol_colors), row=2, col=1)

    hist_colors = ['red' if val >= 0 else 'green' for val in hist_data['Histogram']]
    fig.add_trace(go.Bar(x=hist_data.index, y=hist_data['Histogram'], name='MACD 柱狀圖', marker_color=hist_colors), row=3, col=1)
    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['MACD'], mode='lines', name='MACD 快線', line=dict(color='blue')), row=3, col=1)
    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Signal'], mode='lines', name='MACD 慢線', line=dict(color='orange')), row=3, col=1)

    fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['RSI'], mode='lines', name='RSI (14)', line=dict(color='purple')), row=4, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=4, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=4, col=1)

    fig.update_layout(xaxis_rangeslider_visible=False, xaxis2_rangeslider_visible=False, xaxis3_rangeslider_visible=False, xaxis4_rangeslider_visible=False, height=950, margin=dict(l=0, r=40, t=30, b=0), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # ==========================================
    # 7. 基本面新聞與 AI 戰略分析區
    # ==========================================
    st.subheader("🤖 AI 每日新聞解讀與戰略分析")
    col_news, col_ai = st.columns([1, 1])
    safe_news_titles = []
    fb_intel_text = "" 

    with col_news:
        st.write("**📰 近期重要新聞 (來源: Yahoo)**")
        try:
            yf_rss_url = f"https://finance.yahoo.com/rss/headline?s={ticker_symbol}"
            yf_feed = feedparser.parse(yf_rss_url)
            if yf_feed.entries:
                for entry in yf_feed.entries[:3]:
                    safe_news_titles.append(entry.title) 
                    st.markdown(f"➤ [{entry.title}]({entry.link})") 
            else:
                st.write("目前找不到相關新聞。")
        except Exception as e:
            st.write("讀取 Yahoo 新聞失敗。")
        
        st.markdown("---")
        st.write("**🌍 媒體聚合 (國內外新聞)**")
        try:
            gn_url = f"https://news.google.com/rss/search?q={ticker_symbol}+stock&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            gn_feed = feedparser.parse(gn_url)
            if gn_feed.entries:
                for entry in gn_feed.entries[:3]:
                    safe_news_titles.append(entry.title)
                    st.markdown(f"➤ [{entry.title}]({entry.link})")
            else:
                st.write("目前找不到相關聚合新聞。")
        except Exception as e:
            st.write("讀取媒體聚合失敗。")

        if rss_url:
            st.markdown("---")
            st.write(f"**🌐 社群動態追蹤 (歷史軌跡: {ticker_symbol})**")
            try:
                feed = feedparser.parse(rss_url)
                if feed.entries:
                    target_texts = []
                    fetched_titles = []
                    one_year_ago = datetime.now() - timedelta(days=365)
                    for entry in feed.entries:
                        entry_date = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            entry_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        if entry_date >= one_year_ago:
                            clean_text = re.sub('<[^<]+>', '', entry.summary)
                            base_ticker = ticker_symbol.split('.')[0]
                            # 雙重驗證：代碼或中文名稱
                            if (base_ticker in clean_text or base_ticker in entry.title or 
                                (company_name and company_name in clean_text) or 
                                (company_name and company_name in entry.title)):
                                date_str = entry_date.strftime('%Y-%m-%d')
                                title = entry.title if hasattr(entry, 'title') else "無標題動態"
                                target_texts.append(f"【發布日期：{date_str}】\n{clean_text[:2000]}")
                                fetched_titles.append(f"{date_str} | {title}")
                    if target_texts:
                        fb_intel_text = "\n\n---\n\n".join(target_texts)[:5000]
                        st.success(f"➤ 成功攔截 {len(target_texts)} 篇相關動態！已交由 AI 分析。")
                        with st.expander("👀 點擊查看已攔截的貼文標題"):
                            for t in fetched_titles:
                                st.markdown(f"- {t}")
                    else:
                        st.info(f"近期公開貼文中，暫未搜尋到關於 **{ticker_symbol}** 的討論。")
                else:
                    st.write("目前沒有抓取到最新動態。")
            except Exception as e:
                st.error("讀取社群動態失敗。")

        if ceo_rss_url:
            st.markdown("---")
            st.write(f"**🐦 市場情緒與重訊追蹤**")
            try:
                ceo_feed = feedparser.parse(ceo_rss_url)
                if ceo_feed.entries:
                    ceo_texts = []
                    ceo_titles = []
                    thirty_days_ago = datetime.now() - timedelta(days=30)
                    for entry in ceo_feed.entries:
                        entry_date = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            entry_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        if entry_date >= thirty_days_ago:
                            clean_text = re.sub('<[^<]+>', '', entry.summary)
                            date_str = entry_date.strftime('%Y-%m-%d')
                            title = entry.title if hasattr(entry, 'title') else "無標題推文"
                            ceo_texts.append(f"【官方發布日期：{date_str}】\n{clean_text[:1000]}")
                            ceo_titles.append(f"{date_str} | {title}")
                            if len(ceo_texts) >= 3: 
                                break
                    if ceo_texts:
                        fb_intel_text += "\n\n【官方/論壇動態】：\n" + "\n".join(ceo_texts) 
                        st.success(f"➤ 成功攔截 {len(ceo_texts)} 篇近期動態！")
                        with st.expander("👀 點擊查看發文標題"):
                            for t in ceo_titles:
                                st.markdown(f"- {t}")
                    else:
                        st.info("近期暫無動態。")
                else:
                    st.write("目前沒有抓取到最新動態。")
            except Exception as e:
                st.error("讀取失敗。")

    with col_ai:
        st.write("**🤖 Gemini 綜合戰略分析與專屬助理**")
        if api_key:
            genai.configure(api_key=api_key)
            if st.button("✨ 點我生成 AI 戰略報告", use_container_width=True):
                try:
                    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    if not available_models:
                        st.error("這個 API Key 找不到支援的模型，請確認是否有開通權限。")
                    else:
                        model_name = next((m for m in available_models if 'flash' in m or 'pro' in m), available_models[0])
                        model = genai.GenerativeModel(model_name)
                        
                        latest_rsi = hist_data['RSI'].iloc[-1] if 'RSI' in hist_data else 0
                        latest_macd = hist_data['MACD'].iloc[-1] if 'MACD' in hist_data else 0
                        latest_signal = hist_data['Signal'].iloc[-1] if 'Signal' in hist_data else 0
                        latest_upper = hist_data['Upper_Band'].iloc[-1] if 'Upper_Band' in hist_data else 0
                        latest_lower = hist_data['Lower_Band'].iloc[-1] if 'Lower_Band' in hist_data else 0
                        
                        news_text = "\n".join(safe_news_titles) if safe_news_titles else "今日無重大新聞"
                        kol_context_str = f"\n\n【獨家付費情報 (文字/PDF)】：\n{kol_text}" if kol_text else ""
                        fb_context_str = f"\n\n【公開社群動態 (歷史軌跡)】：\n{fb_intel_text}" if fb_intel_text else ""
                        
                        prompt = f"""你是一位頂尖的台股量化分析師。
請根據 {ticker_symbol} 的最新全方位數據與情報進行深度綜合判斷：

【量化技術數據】：
- 最新收盤價：NT$ {current_price:.2f}
- 布林通道 (20, 2)：上軌 {latest_upper:.2f} / 下軌 {latest_lower:.2f}
- RSI (14)：{latest_rsi:.2f} (若大於70為超買，小於30為超賣)
- MACD 快線：{latest_macd:.2f} / 慢線：{latest_signal:.2f}

【最新新聞與社群情報】：
{news_text}
{kol_context_str}
{fb_context_str}

請撰寫一份專業的綜合戰略報告，嚴格按照以下「三個區塊」結構化輸出，並使用繁體中文（台灣）：
### 1. 📈 技術面診斷
### 2. 📰 基本面與社群情報提煉
### 3. 🎯 全局戰略綜合決策
"""
                        loading_msg = f'系統已自動鎖定 {model_name}，正在為您整合情報...'
                        if kol_pdf is not None:
                            loading_msg = f'系統自動鎖定 {model_name}，研讀 PDF 中...'

                        with st.spinner(loading_msg):
                            contents = [prompt]
                            if kol_pdf is not None:
                                pdf_data = {"mime_type": "application/pdf", "data": kol_pdf.getvalue()}
                                contents.append(pdf_data)
                                
                            response = model.generate_content(contents)
                            # 儲存報告到對話記憶
                            st.session_state.chat_history = [{"role": "model", "content": response.text.replace('$', r'\$')}]
                            
                except Exception as e:
                    st.error(f"API 呼叫失敗: {e}")

            # 顯示對話歷史
            for msg in st.session_state.chat_history:
                role_icon = "🤖" if msg["role"] == "model" else "👤"
                with st.chat_message(msg["role"], avatar=role_icon):
                    st.markdown(msg["content"])

            # 追問輸入框
            if user_question := st.chat_input("對上述報告有疑問嗎？請直接發問..."):
                if not st.session_state.chat_history:
                    st.warning("👈 請先點擊上方「生成 AI 戰略報告」，才能進行追問喔！")
                else:
                    st.session_state.chat_history.append({"role": "user", "content": user_question})
                    with st.chat_message("user", avatar="👤"):
                        st.markdown(user_question)

                    with st.chat_message("model", avatar="🤖"):
                        with st.spinner("思考中..."):
                            try:
                                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                                model_name = next((m for m in available_models if 'flash' in m or 'pro' in m), available_models[0])
                                model = genai.GenerativeModel(model_name)
                                history_for_gemini = [{"role": m["role"], "parts": [m["content"]]} for m in st.session_state.chat_history[:-1]]
                                chat = model.start_chat(history=history_for_gemini)
                                response = chat.send_message(user_question)
                                st.markdown(response.text.replace('$', r'\$'))
                                st.session_state.chat_history.append({"role": "model", "content": response.text.replace('$', r'\$')})
                            except Exception as e:
                                st.error(f"追問失敗: {e}")
        else:
            st.warning("⚠️ 請在左側輸入 Gemini API Key 以啟動 AI 自動分析功能。")

    # ==========================================
    # 8. 頁尾版權宣告與專屬署名 (Footer)
    # ==========================================
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #888888; font-size: 14px;'>
            Designed & Built with 💡 by <b>Paul Wang</b> | 專屬 AI 台股分析儀表板 © 2026
        </div>
        """,
        unsafe_allow_html=True
    )
