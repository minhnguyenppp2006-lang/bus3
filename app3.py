import streamlit as st
import openrouteservice
import google.generativeai as genai
from geopy.geocoders import Nominatim
import speech_recognition as sr
from gtts import gTTS
from streamlit_mic_recorder import mic_recorder
import io
import tempfile
import os

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="Bus Assistant (Free & Geopy)", page_icon="🚌", layout="wide")

# --- LẤY API KEY TỪ SECRETS HOẶC NHẬP TAY ---
try:
    # Ưu tiên lấy từ secrets
    ORS_API_KEY = st.secrets.get("ORS_API_KEY", "")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    # Nếu chạy local chưa có file secrets
    ORS_API_KEY = ""
    GEMINI_API_KEY = ""

# --- SIDEBAR CẤU HÌNH ---
with st.sidebar:
    st.header("⚙️ Cấu hình")
    
    # Nếu chưa có Key trong secrets thì hiện ô nhập
    if not ORS_API_KEY:
        ORS_API_KEY = st.text_input("Nhập OpenRouteService Key", type="password")
        st.caption("[Lấy Key miễn phí tại đây](https://openrouteservice.org/dev/#/home)")
        
    if not GEMINI_API_KEY:
        GEMINI_API_KEY = st.text_input("Nhập Gemini API Key", type="password")
        st.caption("[Lấy Key miễn phí tại đây](https://aistudio.google.com/)")

    auto_speak = st.toggle("🔊 Đọc to câu trả lời", value=True)
    st.info("Phiên bản sử dụng Geopy để định vị tốt hơn.")

# --- HÀM XỬ LÝ ĐỊA LÝ (GEOPY + ORS) ---

def get_coordinates(address):
    """
    Dùng Geopy (Nominatim) để tìm tọa độ từ địa chỉ.
    Không cần API Key, tìm tiếng Việt tốt.
    """
    # User_agent là bắt buộc để định danh ứng dụng của bạn
    geolocator = Nominatim(user_agent="vietnam_bus_assistant_app_v1")
    
    try:
        # Thêm 'Việt Nam' để tìm chính xác hơn nếu người dùng quên nhập
        search_query = address
        if "việt nam" not in address.lower():
            search_query += ", Việt Nam"
            
        location = geolocator.geocode(search_query, timeout=10)
        
        if location:
            # Lưu ý: ORS cần [Longitude, Latitude] (Kinh độ trước)
            # Geopy trả về (Latitude, Longitude) (Vĩ độ trước) -> Cần đảo ngược
            return [location.longitude, location.latitude], location.address
        return None, None
    except Exception as e:
        return None, str(e)

def get_route_ors(start_addr, end_addr, client):
    """Tìm đường đi bộ/xe kết hợp Geopy và OpenRouteService"""
    
    # 1. Định vị (Geocoding)
    start_coords, start_full = get_coordinates(start_addr)
    end_coords, end_full = get_coordinates(end_addr)
    
    # Xử lý lỗi định vị
    if not start_coords:
        return None, f"Không tìm thấy điểm đi: '{start_addr}'. Hãy thử nhập cụ thể hơn (VD: Số nhà, Phường, Quận)."
    if not end_coords:
        return None, f"Không tìm thấy điểm đến: '{end_addr}'. Hãy thử nhập cụ thể hơn."

    try:
        # 2. Vẽ đường (Routing)
        # profile='foot-walking' (đi bộ) hoặc 'driving-car' (xe hơi)
        route = client.directions(
            coordinates=[start_coords, end_coords],
            profile='foot-walking', 
            format='geojson',
            language='vi'
        )
        
        # 3. Trích xuất dữ liệu
        summary = route['features'][0]['properties']['segments'][0]
        distance_km = round(summary['distance'] / 1000, 2)
        duration_min = round(summary['duration'] / 60)
        
        # Lấy các bước đi
        steps_list = []
        for step in summary['steps']:
            steps_list.append(f"- {step['instruction']} ({step['distance']}m)")
            
        steps_str = "\n".join(steps_list)

        return {
            "start_original": start_addr,
            "end_original": end_addr,
            "start_found": start_full,
            "end_found": end_full,
            "distance": f"{distance_km} km",
            "duration": f"{duration_min} phút đi bộ",
            "steps": steps_str
        }, None

    except Exception as e:
        return None, f"Lỗi tìm đường ORS: {str(e)}"

# --- HÀM XỬ LÝ ÂM THANH ---
def text_to_speech(text):
    try:
        if not text: return None
        tts = gTTS(text=text, lang='vi')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        return fp
    except: return None

def process_audio_input(audio_bytes):
    r = sr.Recognizer()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            tmp_name = tmp.name
        with sr.AudioFile(tmp_name) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data, language="vi-VN")
        os.remove(tmp_name)
        return text
    except: return None

# --- GIAO DIỆN CHÍNH ---

st.title("🚌 Bus Assistant AI (Geopy Version)")
st.caption("Định vị bằng Nominatim - Tìm đường bằng OpenRouteService - Tư vấn bằng Gemini")

# Kiểm tra Key
if not ORS_API_KEY or not GEMINI_API_KEY:
    st.warning("⚠️ Vui lòng nhập đủ API Key ở thanh bên trái (Sidebar) để bắt đầu.")
    st.stop()

# Khởi tạo Client
ors_client = openrouteservice.Client(key=ORS_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-flash-latest') # Dùng bản Flash cho nhanh và Free

# Chia cột
col1, col2 = st.columns([1, 1])

# --- CỘT TRÁI: TÌM KIẾM ---
with col1:
    st.subheader("📍 Lộ Trình")
    start_input = st.text_input("Điểm đi", placeholder="VD: Bến xe Miền Tây")
    end_input = st.text_input("Điểm đến", placeholder="VD: Đại học Quốc gia TPHCM")
    
    if st.button("Tìm đường 🚀", type="primary"):
        if start_input and end_input:
            with st.spinner("Đang định vị và tính toán..."):
                data, error = get_route_ors(start_input, end_input, ors_client)
                
                if error:
                    st.error(error)
                else:
                    # Hiển thị kết quả
                    st.success("Đã tìm thấy lộ trình!")
                    st.write(f"**Từ:** {data['start_found']}")
                    st.write(f"**Đến:** {data['end_found']}")
                    
                    m1, m2 = st.columns(2)
                    m1.metric("Khoảng cách", data['distance'])
                    m2.metric("Thời gian đi bộ", data['duration'])
                    
                    # Lưu context vào session
                    context_str = f"""
                    Thông tin chuyến đi:
                    - Điểm đi: {data['start_found']}
                    - Điểm đến: {data['end_found']}
                    - Khoảng cách thực tế: {data['distance']}
                    - Thời gian nếu đi bộ: {data['duration']}
                    """
                    st.session_state['route_context'] = context_str
                    
                    with st.expander("Chi tiết đường đi bộ (Tham khảo)"):
                        st.text(data['steps'])
        else:
            st.toast("Vui lòng nhập cả điểm đi và đến!")

# --- CỘT PHẢI: AI CHAT ---
with col2:
    st.subheader("💬 Trợ Lý Ảo")
    
    chat_container = st.container(height=400)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Chào bạn! Hãy tìm lộ trình bên trái, sau đó tôi sẽ gợi ý tuyến xe buýt phù hợp."}]
        
    for msg in st.session_state.messages:
        chat_container.chat_message(msg["role"]).write(msg["content"])
        
    # Input khu vực
    c_input, c_mic = st.columns([5, 1])
    user_text = c_input.chat_input("Hỏi tôi về tuyến xe buýt...")
    with c_mic:
        st.write("") # Spacer
        st.write("")
        mic_data = mic_recorder(start_prompt="🎤", stop_prompt="⏹️", key='mic', use_container_width=True)
    
    # Xử lý input
    final_prompt = user_text
    
    # Logic xử lý Mic
    if mic_data and ('last_mic_id' not in st.session_state or st.session_state.last_mic_id != mic_data['id']):
        st.session_state.last_mic_id = mic_data['id']
        text_from_audio = process_audio_input(mic_data['audio']['bytes'])
        if text_from_audio:
            final_prompt = text_from_audio
    
    if final_prompt:
        # Hiển thị User
        st.session_state.messages.append({"role": "user", "content": final_prompt})
        chat_container.chat_message("user").write(final_prompt)
        
        # Gọi AI
        try:
            current_context = st.session_state.get('route_context', 'Người dùng chưa nhập lộ trình cụ thể.')
            
            # Prompt kỹ thuật (Prompt Engineering)
            system_prompt = f"""
            Bạn là trợ lý giao thông công cộng thông minh tại Việt Nam.
            Dữ liệu hệ thống cung cấp: {current_context}
            
            YÊU CẦU:
            1. Dựa vào điểm đi và đến trong dữ liệu (nếu có), hãy dùng kiến thức có sẵn của bạn để ĐỀ XUẤT CÁC TUYẾN XE BUÝT (Bus numbers) phù hợp nhất.
            2. Nếu khoảng cách > 10km, hãy nhắc người dùng chuẩn bị lộ trình dài.
            3. Trả lời câu hỏi: "{final_prompt}"
            4. Phong cách: Ngắn gọn, hữu ích, tiếng Việt tự nhiên.
            """
            
            response = model.generate_content(system_prompt).text
            
            # Hiển thị AI
            st.session_state.messages.append({"role": "assistant", "content": response})
            chat_container.chat_message("assistant").write(response)
            
            # Đọc to
            if auto_speak:
                audio_file = text_to_speech(response)
                if audio_file:
                    st.audio(audio_file, format='audio/mp3', start_time=0)
                    
        except Exception as e:
            st.error(f"AI Error: {e}")