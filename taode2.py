import json
import os
import sys
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

# Config chung
base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, "template")
html_template_name = "index.jinja2"
# --- CẤU HÌNH GIAO DIỆN CHUẨN WORD (CSS) ---


env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
t = env.get_template(html_template_name)

def select_file():
    """Mở hộp thoại chọn file JSON"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Chọn file JSON đề thi",
        filetypes=[("JSON Files", "*.json")]
    )
    return file_path

def main():
    # 1. Chọn file
    print(">>> Đang mở hộp thoại chọn file...")
    json_path = select_file()
    
    if not json_path:
        print(">>> Hủy bỏ: Chưa chọn file.")
        return

    base_dir = os.path.dirname(json_path) # Thư mục chứa file json
    file_name_no_ext = os.path.splitext(os.path.basename(json_path))[0]
    output_pdf_path = os.path.join(base_dir, f"{file_name_no_ext}.pdf")

    # 2. Đọc dữ liệu
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Lỗi đọc file JSON: {e}")
        return

    # 3. Xử lý đường dẫn ảnh
    for item in data:
        # Tạo một list mới trong item để chứa các đường dẫn tuyệt đối
        item["image_abspaths"] = [] 
        
        # Lấy list ảnh gốc ra (nếu không có thì trả về list rỗng [])
        raw_images_list = item.get("images", [])
        
        # Nếu có ảnh (list không rỗng)
        if raw_images_list:
            for img_name in raw_images_list:
                # Ghép đường dẫn cho TỪNG ảnh
                abs_path = os.path.join(base_dir, img_name)
                
                # Sửa dấu \ thành / và thêm vào list kết quả
                clean_path = abs_path.replace("\\", "/")
                item["image_abspaths"].append(clean_path)

    # 4. Render HTML trong bộ nhớ (không cần lưu file html ra đĩa)
    print(">>> Đang tạo giao diện chuẩn Word...")
    html_content = t.render(questions=data)

    output_html_path = os.path.join(base_dir, f"{file_name_no_ext}.html")
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    # 5. Xuất ra PDF bằng Playwright
    print(">>> Đang in ra PDF (Vui lòng đợi vài giây)...")
    try:
        with sync_playwright() as p:
            # Mở trình duyệt ẩn
            browser = p.chromium.launch()
            page = browser.new_page()
            
            # Load nội dung HTM
            page.goto(f"file:///{output_html_path}")
            
            # Lệnh "Thần thánh": Chờ cho đến khi mạng rảnh (tức là ảnh đã load xong)
            page.wait_for_load_state("networkidle")
            
            # Cấu hình xuất PDF
            page.pdf(
                path=output_pdf_path,
                format="A4",
                print_background=True, # In cả màu nền (nếu có)
                margin={ # Lề giấy (ghi đè CSS nếu cần, nhưng CSS @page mạnh hơn)
                    "top": "0cm", # Để 0 vì đã chỉnh trong CSS @page
                    "bottom": "0cm",
                    "left": "0cm",
                    "right": "0cm"
                }
            )
            browser.close()
            
        print("-" * 40)
        print(f"✅ XONG! File PDF đã được tạo tại:")
        print(output_pdf_path)
        
        # Tự động mở file (Windows)
        os.startfile(output_pdf_path)
        
    except Exception as e:
        print(f"❌ Lỗi khi xuất PDF: {e}")


def ensure_browsers_installed():
    """Tự động cài Chromium nếu chưa có"""
    print(">>> Đang kiểm tra môi trường Playwright...")
    try:
        # Thử chạy lệnh kiểm tra xem trình duyệt có chưa (hoặc chạy lệnh install luôn cho chắc)
        # Lệnh này sẽ cài chromium nếu thiếu, nếu có rồi thì nó bỏ qua rất nhanh
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print(">>> Môi trường Playwright đã sẵn sàng!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi cài đặt trình duyệt: {e}")
        sys.exit(1)

if __name__ == "__main__":
    ensure_browsers_installed()
    main()