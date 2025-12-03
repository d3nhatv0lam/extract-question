import os
import json
import tkinter as tk
from tkinter import filedialog
from jinja2 import Environment, FileSystemLoader
from livereload import Server

# --- 1. CẤU HÌNH ĐƯỜNG DẪN (Tính 1 lần dùng chung) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) # Thư mục chứa file .py này
PARENT_DIR = os.path.dirname(SCRIPT_DIR)                # Thư mục cha (Project Root)

# Cấu hình template
TEMPLATE_DIR_NAME = "template"
TEMPLATE_FILE_NAME = "index.jinja2"
OUTPUT_FILE_NAME = "index.html"

# Đường dẫn tuyệt đối (Dùng xuyên suốt chương trình)
TEMPLATE_FOLDER_PATH = os.path.join(PARENT_DIR, TEMPLATE_DIR_NAME)
TEMPLATE_FULL_PATH = os.path.join(TEMPLATE_FOLDER_PATH, TEMPLATE_FILE_NAME)
OUTPUT_FILE_PATH = os.path.join(SCRIPT_DIR, OUTPUT_FILE_NAME)

# --- 2. DỮ LIỆU MẪU (FALLBACK) ---
MOCK_DATA = [
    {
        "question": "Câu hỏi mẫu (Do bạn chưa chọn file JSON): 1 + 1 = ?",
        "options": ["1", "2", "3", "4"],
        "correct_index": 1,
        "image_abspaths": []
    },
    {
        "question": "Koala sống ở đâu? (Có ảnh minh họa)",
        "options": ["Mỹ", "Úc", "Việt Nam", "Pháp"],
        "correct_index": 1,
        # Lưu ý: Thay đường dẫn ảnh thật trên máy bạn để test
        "image_abspaths": ["C:/Windows/Web/Screen/img100.jpg"] 
    }
]

# Biến toàn cục để lưu dữ liệu đang dùng (JSON hoặc MOCK)
CURRENT_DATA = []

# --- 3. CÁC HÀM XỬ LÝ ---

def load_data_source():
    """Mở hộp thoại chọn JSON. Trả về data từ file hoặc Mock data."""
    print(">>> Đang khởi động hộp thoại chọn file...")
    
    # Ẩn cửa sổ chính của Tkinter
    root = tk.Tk()
    root.withdraw()
    
    file_path = filedialog.askopenfilename(
        title="Chọn file dữ liệu JSON (Cancel để dùng dữ liệu mẫu)",
        filetypes=[("JSON Files", "*.json")]
    )
    
    if file_path:
        print(f">>> Đã chọn file: {os.path.basename(file_path)}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # Xử lý đường dẫn ảnh trong JSON nếu cần (tương tự script trước)
                # Ở đây mình giả định JSON đã có sẵn image_abspaths hoặc bạn load thô
                return json.load(f)
        except Exception as e:
            print(f"❌ Lỗi đọc file JSON: {e}. Chuyển về dùng Mock Data.")
    else:
        print(">>> Bạn đã hủy chọn file. Đang sử dụng DỮ LIỆU MẪU (Mock Data).")
    
    root.destroy()
    return MOCK_DATA

def render_html():
    """Hàm render, sẽ được gọi lại mỗi khi file template thay đổi"""
    print(">>> ♻️  Đang render lại HTML...")
    
    # Setup Jinja2 Environment
    env = Environment(loader=FileSystemLoader(TEMPLATE_FOLDER_PATH), autoescape=True)
    
    try:
        template = env.get_template(TEMPLATE_FILE_NAME)
        
        # Render với dữ liệu hiện tại (Global variable)
        html_content = template.render(questions=CURRENT_DATA)
        
        with open(OUTPUT_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(html_content)
            
    except Exception as e:
        print(f"❌ Lỗi Render: {e}")

def main():
    global CURRENT_DATA # Khai báo dùng biến toàn cục
    
    # 1. Load dữ liệu đầu vào
    CURRENT_DATA = load_data_source()
    
    # 2. Render lần đầu tiên
    render_html()
    
    # 3. Khởi tạo Live Server
    server = Server()
    
    print(f"\n--- THÔNG TIN CẤU HÌNH ---")
    print(f"• Template Folder: {TEMPLATE_FOLDER_PATH}")
    print(f"• Watching File:   {TEMPLATE_FULL_PATH}")
    print(f"--------------------------\n")

    # Canh chừng file template (Dùng đường dẫn tuyệt đối đã tính ở trên)
    server.watch(TEMPLATE_FULL_PATH, render_html)
    
    # Mẹo: Nếu muốn canh cả file CSS nằm cùng folder template
    # css_path = os.path.join(TEMPLATE_FOLDER_PATH, "style.css")
    # server.watch(css_path, render_html)

    # Mở trình duyệt
    print(f">>> 🚀 Server đang chạy tại: http://127.0.0.1:5500/{OUTPUT_FILE_NAME}")
    server.serve(port=5500, root=SCRIPT_DIR, open_url_delay=1)

if __name__ == "__main__":
    main()