import streamlit as st
import fitz  # PyMuPDF
import re
import json
import io
import docx
import zipfile
from PIL import Image
from collections import Counter

# --- PHẦN 1: CÔNG CỤ XỬ LÝ (UTILS) ---

def normalize_text(text):
    """Làm sạch văn bản, xử lý các ký tự ẩn"""
    if not text: return ""
    # Thay thế các ký tự space đặc biệt thành space thường
    return text.replace('\xa0', ' ').replace('\u200b', '').replace('\t', ' ')

def is_underlined(word_rect, drawings):
    """
    Kiểm tra gạch chân (Logic hình học)
    word_rect: [x0, y0, x1, y1]
    """
    wx0, wy0, wx1, wy1 = word_rect
    w_center_y = (wy0 + wy1) / 2
    
    for line in drawings:
        lx0, ly0, lx1, ly1 = line
        # 1. Vertical Check: Line nằm dưới tâm chữ, cách chân không quá 12px
        if not (w_center_y < ly0 < wy1 + 12): 
            continue
        # 2. Horizontal Check: Giao nhau ít nhất 2px
        if min(wx1, lx1) > max(wx0, lx0) + 2: 
            return True
    return False

# --- PHẦN 2: CORE ENGINE (V18 - CALIBRATED LAYOUT) ---

def process_pdf_v18(file_stream):
    doc = fitz.open(stream=file_stream.read(), filetype="pdf")
    
    full_text = ""
    extracted_images_map = {} 
    current_q_id = 0
    
    for page in doc:
        # --- A. LẤY ẢNH GỐC (NATIVE IMAGES) ---
        # Logic: Đi tới đâu tìm ảnh tới đó
        image_infos = page.get_image_info(xrefs=True)
        image_infos.sort(key=lambda x: x['bbox'][1]) # Sort theo chiều dọc (Y)
        
        # Lọc bỏ ảnh quá nhỏ (icon, đường kẻ trang trí)
        pending_images = [img for img in image_infos if (img['bbox'][3] - img['bbox'][1]) > 20]

        # --- B. LẤY ĐƯỜNG KẺ (CHO GẠCH CHÂN) ---
        drawings = []
        for path in page.get_drawings():
            for item in path["items"]:
                if item[0] == "l": # Line
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 2: 
                        drawings.append([min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y)])
                elif item[0] == "re": # Rect
                    r = item[1]
                    if abs(r.height) < 5: 
                        drawings.append([r.x0, r.y0, r.x1, r.y1])

        # --- C. LẤY TEXT & TÍNH TOÁN LAYOUT CHUẨN ---
        words = page.get_text("words")
        # Sort ưu tiên Y (dòng), sau đó X (trái qua phải)
        # round(w[1]) giúp gom các từ lệch nhau < 1px vào cùng 1 dòng
        words.sort(key=lambda w: (round(w[1]), w[0])) 
        
        # --- THUẬT TOÁN TÌM LỀ CHUẨN (SMART MARGIN) ---
        # Chỉ lấy x0 của các từ ĐẦU TIÊN trong mỗi dòng để tính lề
        line_starters = []
        last_y_check = -999
        for w in words:
            if abs(w[1] - last_y_check) > 5: # Đây là từ bắt đầu dòng mới
                line_starters.append(round(w[0]))
                last_y_check = w[1]
        
        # Lấy giá trị X xuất hiện nhiều nhất làm lề trái chuẩn (Base Margin)
        base_margin = Counter(line_starters).most_common(1)[0][0] if line_starters else 0
        
        # --- BẮT ĐẦU QUÉT DÒNG ---
        last_y = -999
        page_clean_text = ""
        current_line_text = "" 
        
        for i, w in enumerate(words):
            text = w[4]
            rect = [w[0], w[1], w[2], w[3]]
            current_y = w[1]
            
            # 1. Check Gạch chân (Đáp án đúng)
            if re.match(r'^[A-D][\.\)]?$', text):
                clean_char = text[0]
                if is_underlined(rect, drawings):
                    text = text.replace(clean_char, f"[[{clean_char}]]")

            # 2. Logic Ngắt dòng Header (Active Break)
            force_newline = False
            if text == "Câu" and i < len(words) - 1:
                next_text = words[i+1][4]
                if re.match(r'^\d+[:\.]?$', next_text):
                    force_newline = True

            # 3. Xử lý xuống dòng & Thụt lề
            # Nếu khoảng cách Y > 5px -> Coi là dòng mới
            if abs(current_y - last_y) > 5 or force_newline: 
                
                # Check ID câu hỏi từ dòng trước
                match_q = re.match(r'^\s*Câu\s+(\d+)', current_line_text)
                if match_q: current_q_id = int(match_q.group(1))
                
                current_line_text = ""
                
                # --- TÍNH THỤT ĐẦU DÒNG (CALIBRATED) ---
                indent_pixel = w[0] - base_margin
                
                # Ngưỡng (Threshold): Chỉ thụt nếu lệch > 10px (tránh lệch li ti do canh lề)
                # Hệ số (Divisor): 7.0 (Chiều rộng trung bình 1 ký tự)
                if indent_pixel > 10:
                    num_spaces = int(indent_pixel / 7.0) 
                else:
                    num_spaces = 0
                
                indent_str = " " * num_spaces
                
                page_clean_text += "\n" + indent_str + text
                current_line_text += text
                last_y = current_y
            else:
                # Cùng dòng
                page_clean_text += " " + text
                current_line_text += " " + text
            
            # 4. Logic Gán Ảnh (Scan & Match)
            # Kiểm tra ảnh nằm ngang hàng hoặc ngay trên dòng chữ này
            images_to_assign = []
            for img in pending_images[:]:
                img_top = img['bbox'][1]
                # Nếu Top ảnh <= Top chữ + 15px (nghĩa là ảnh xuất hiện trước hoặc ngang chữ)
                if img_top <= (current_y + 15):
                    if current_q_id > 0:
                        images_to_assign.append(img)
                        pending_images.remove(img)
            
            if images_to_assign:
                for img_info in images_to_assign:
                    try:
                        base_img = doc.extract_image(img_info['xref'])
                        pil_img = Image.open(io.BytesIO(base_img["image"]))
                        if current_q_id not in extracted_images_map:
                            extracted_images_map[current_q_id] = []
                        extracted_images_map[current_q_id].append(pil_img)
                    except: pass

        # Clean up ảnh cuối trang
        if pending_images and current_q_id > 0:
             for img_info in pending_images:
                try:
                    base_img = doc.extract_image(img_info['xref'])
                    pil_img = Image.open(io.BytesIO(base_img["image"]))
                    if current_q_id not in extracted_images_map: extracted_images_map[current_q_id] = []
                    extracted_images_map[current_q_id].append(pil_img)
                except: pass
                
        full_text += page_clean_text + "\n"

    return full_text, extracted_images_map

# --- PHẦN 3: JSON PARSING ---

def parse_quiz_json_v18(raw_text, img_map):
    text = normalize_text(raw_text)
    raw_questions = re.split(r'(?:\n|^)(?=\s*Câu\s+\d+[:\.])', text)
    quiz_data = []

    for block in raw_questions:
        block = block.rstrip()
        if not block: continue
        
        q_num_match = re.search(r'Câu\s+(\d+)', block)
        if not q_num_match: continue
        q_id = int(q_num_match.group(1))

        question_obj = {
            "id": q_id,
            "question": "",
            "options": [],
            "correct_answer_index": -1,
            "images": []
        }

        # Tìm điểm cắt Đáp án A
        pattern_anchor = r'(?:^|[\s\n])(\s*(?:\[\[A\]\]|A)[\.\)].*)'
        match_anchor = re.search(pattern_anchor, block, re.DOTALL)

        if match_anchor:
            split_idx = match_anchor.start(1)
            q_part = block[:split_idx]
            opts_part = block[split_idx:]
        else:
            q_part = block; opts_part = ""

        # Clean câu hỏi (Giữ Indent)
        lines = q_part.split('\n')
        cleaned_lines = []
        for line in lines:
            if re.match(r'^\s*Câu\s+\d+', line):
                line = re.sub(r'^\s*Câu\s+\d+[:\.]?\s*', '', line)
            if line.strip(): cleaned_lines.append(line)
        question_obj["question"] = "\n".join(cleaned_lines).strip('\n')

        # Parse Options
        if opts_part:
            marker_iter = re.finditer(r'(?:^|[\s])((?:\[\[([A-D])\]\]|([A-D]))[\.\)])', opts_part)
            markers = []
            for m in marker_iter:
                markers.append({'full': m.group(1), 'char': m.group(2) or m.group(3), 'start': m.start(1), 'end': m.end()})
            markers.sort(key=lambda x: x['start'])
            
            parsed_opts = {"A":"", "B":"", "C":"", "D":""}
            correct_char = None
            for i, m in enumerate(markers):
                char = m['char']
                if '[[' in m['full']: correct_char = char
                start = m['end']
                end = markers[i+1]['start'] if i < len(markers)-1 else len(opts_part)
                parsed_opts[char] = opts_part[start:end].strip()
            
            question_obj["options"] = [parsed_opts.get(k, "") for k in "ABCD"]
            if correct_char: question_obj["correct_answer_index"] = ord(correct_char) - ord('A')

        if q_id in img_map:
            for idx, _ in enumerate(img_map[q_id]):
                question_obj["images"].append(f"image_q{q_id}_{idx+1}.png")
        
        quiz_data.append(question_obj)

    return quiz_data

def create_zip(json_data, img_map):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
        zf.writestr("quiz_data.json", json.dumps(json_data, ensure_ascii=False, indent=4))
        for q_id, imgs in img_map.items():
            for idx, img in enumerate(imgs):
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                zf.writestr(f"image_q{q_id}_{idx+1}.png", buf.getvalue())
    return zip_buffer.getvalue()

def extract_text_docx(file):
    try:
        doc = docx.Document(file)
        full_text = []
        for para in doc.paragraphs:
            para_text = ""
            for run in para.runs:
                text = run.text
                if run.underline or run.bold: 
                    if re.match(r'^\s*[A-D][\.\)]?\s*$', text) or re.match(r'^\s*[A-D]\s*$', text):
                         char = text.strip()[0]; rest = text.strip()[1:]
                         text = f"[[{char}]]{rest}"
                para_text += text
            full_text.append(para_text)
        return "\n".join(full_text)
    except Exception as e: return f"Error: {str(e)}"

# --- UI STREAMLIT ---

st.set_page_config(page_title="Quiz Pro V18", layout="wide")
st.title("🚀 Quiz Extractor V18 (Calibrated Layout)")
st.markdown("Bản cập nhật: **Chuẩn hóa thụt đầu dòng (Indentation)** để text trông tự nhiên như PDF gốc.")

col1, col2 = st.columns([1, 1.5])
with col1:
    f = st.file_uploader("Upload File", type=['pdf', 'docx'])
    raw_text = ""; img_map = {}
    if f:
        ext = f.name.split('.')[-1].lower()
        if st.button("🚀 Xử lý", type="primary"):
            with st.spinner("Đang xử lý & Căn chỉnh layout..."):
                if ext == 'pdf':
                    raw_text, img_map = process_pdf_v18(f)
                    st.success("Xử lý hoàn tất!")
                elif ext == 'docx': raw_text = extract_text_docx(f)

    if raw_text:
        with st.expander("🔍 Debug Text (Kiểm tra thụt lề)"): 
            st.text(raw_text[:2000])

with col2:
    if raw_text:
        data = parse_quiz_json_v18(raw_text, img_map)
        
        # Thống kê
        total = len(data)
        with_ans = sum(1 for q in data if q['correct_answer_index'] != -1)
        with_img = sum(1 for q in data if q['images'])
        
        st.metric("Thống kê kết quả", f"{total} Câu hỏi", f"{with_ans} Có đáp án | {with_img} Có hình ảnh")
        
        # Cảnh báo thiếu đáp án
        missing_ids = [q['id'] for q in data if q['correct_answer_index'] == -1]
        if missing_ids:
            st.error(f"⚠️ **Cảnh báo:** Các câu sau chưa tìm thấy đáp án: {', '.join(map(str, missing_ids))}")
        else:
            st.success("✅ Tuyệt vời! Tất cả câu hỏi đều có đáp án.")

        st.divider()

        tab1, tab2 = st.tabs(["👁️ Visual Preview", "📄 JSON Data"])
        with tab1:
            for q in data:
                # Tiêu đề Visual
                status_icons = ""
                has_error = False
                if q['correct_answer_index'] == -1: status_icons += "⚠️ "; has_error = True
                if q['id'] in img_map: status_icons += "📸 "
                
                with st.expander(f"{status_icons}Câu {q['id']}: {q['question'][:60]}...", expanded=has_error):
                    # Hiển thị câu hỏi (đã fix thụt lề)
                    st.code(q['question'], language=None)
                    
                    # Ảnh
                    if q['id'] in img_map:
                        st.info(f"📸 Hình ảnh đính kèm ({len(img_map[q['id']])} ảnh)")
                        for img in img_map[q['id']]: st.image(img, width=400)
                    
                    # Options & Đáp án
                    st.write("**Các lựa chọn:**")
                    st.json(q['options'])
                    
                    idx = q['correct_answer_index']
                    if idx != -1:
                        labels = ["A", "B", "C", "D"]
                        st.success(f"✅ Đáp án đúng: **{labels[idx]}. {q['options'][idx]}**")
                    else:
                        st.error("⚠️ **Chưa tìm thấy đáp án!**")

        with tab2: st.json(data)
        st.download_button("Tải ZIP", create_zip(data, img_map), "quiz_v18.zip", "application/zip", type="primary")