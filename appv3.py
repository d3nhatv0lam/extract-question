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

# --- PHẦN 2: CORE ENGINE (UPDATED - FIX PARSING ERROR) ---

def process_pdf_v18(file_stream):
    doc = fitz.open(stream=file_stream.read(), filetype="pdf")
    
    full_text = ""
    extracted_images_map = {} 
    current_q_id = 0
    
    for page in doc:
        # --- A. LẤY ẢNH & ĐƯỜNG KẺ (GIỮ NGUYÊN) ---
        image_infos = page.get_image_info(xrefs=True)
        image_infos.sort(key=lambda x: x['bbox'][1])
        pending_images = [img for img in image_infos if (img['bbox'][3] - img['bbox'][1]) > 20]

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

        # --- C. LẤY TEXT & XỬ LÝ DÒNG THÔNG MINH ---
        words = page.get_text("words")
        # Sort ban đầu: Y trước, X sau
        words.sort(key=lambda w: (w[1], w[0]))
        
        # --- THUẬT TOÁN GOM DÒNG (LINE GROUPING) ---
        # Thay vì round(), ta gom các từ có Y chênh lệch < 3px vào cùng 1 dòng
        lines = []
        if words:
            current_line = [words[0]]
            for w in words[1:]:
                # Nếu từ này lệch Y so với từ trước đó trong line < 5px -> cùng dòng
                if abs(w[1] - current_line[-1][1]) < 5:
                    current_line.append(w)
                else:
                    lines.append(current_line)
                    current_line = [w]
            lines.append(current_line)

        # Sort lại từng dòng theo X (từ trái qua phải)
        for line in lines:
            line.sort(key=lambda w: w[0])

        # --- TÍNH TOÁN LỀ TRÁI (BASE MARGIN) ---
        line_starters = [round(line[0][0]) for line in lines if line]
        base_margin = Counter(line_starters).most_common(1)[0][0] if line_starters else 0

        # --- BẮT ĐẦU QUÉT TEXT ---
        page_clean_text = ""
        
        for line in lines:
            line_text_parts = []
            
            # Kiểm tra xem dòng này có bắt đầu bằng "Câu X" không
            # Nếu có, ta force thêm \n phía trước để tách biệt hoàn toàn
            first_word_text = line[0][4]
            is_new_question = False
            if first_word_text == "Câu" and len(line) > 1:
                if re.match(r'^\d+[:\.]?$', line[1][4]):
                    is_new_question = True
                    # Cập nhật ID hiện tại
                    try:
                        current_q_id = int(re.sub(r'\D', '', line[1][4]))
                    except: pass

            # Xử lý từng từ trong dòng
            for w in line:
                text = w[4]
                rect = [w[0], w[1], w[2], w[3]]
                
                # Check Gạch chân (Đáp án đúng)
                # Regex bắt: A. hoặc A) hoặc (A)
                if re.match(r'^[\(]?[A-D][\.\)]?$', text):
                    # Lấy ký tự cái (A, B, C, D)
                    clean_char = re.search(r'[A-D]', text).group(0)
                    if is_underlined(rect, drawings):
                        text = text.replace(clean_char, f"[[{clean_char}]]")
                
                line_text_parts.append(text)

            # --- TÍNH THỤT ĐẦU DÒNG CHO CẢ DÒNG ---
            indent_pixel = line[0][0] - base_margin
            num_spaces = int(indent_pixel / 6.0) if indent_pixel > 10 else 0
            indent_str = " " * num_spaces
            
            full_line_str = " ".join(line_text_parts)
            
            # Nếu là câu mới, thêm 2 dấu xuống dòng để regex dễ cắt
            prefix = "\n\n" if is_new_question else "\n"
            
            page_clean_text += prefix + indent_str + full_line_str

            # --- LOGIC GÁN ẢNH (GIỮ NGUYÊN) ---
            # Lấy tọa độ Y trung bình của dòng
            line_y = line[0][1]
            images_to_assign = []
            for img in pending_images[:]:
                img_bottom = img['bbox'][3]
                # Nếu đáy ảnh nằm trên dòng này hoặc ngang dòng này
                if img_bottom <= (line_y + 30): 
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

        full_text += page_clean_text

    # Clean up ảnh còn sót lại ở cuối trang
    if pending_images and current_q_id > 0:
         for img_info in pending_images:
            try:
                base_img = doc.extract_image(img_info['xref'])
                pil_img = Image.open(io.BytesIO(base_img["image"]))
                if current_q_id not in extracted_images_map: extracted_images_map[current_q_id] = []
                extracted_images_map[current_q_id].append(pil_img)
            except: pass

    return full_text, extracted_images_map


# --- PHẦN 3: JSON PARSING (UPDATED - SMART OPTION PARSER) ---

def parse_quiz_json_v18(raw_text, img_map):
    text = normalize_text(raw_text)
    
    # Regex tách các câu hỏi: Tìm chữ "Câu X" ở đầu dòng (nhờ việc đã add \n ở step trước)
    # (?m) bật chế độ multiline
    split_pattern = r'(?:\n\s*|^)(?=Câu\s+\d+[:\.])'
    raw_questions = re.split(split_pattern, text)
    
    quiz_data = []

    for block in raw_questions:
        block = block.strip()
        if not block: continue
        
        # Xác định ID câu hỏi
        q_num_match = re.search(r'^Câu\s+(\d+)', block)
        if not q_num_match: continue
        q_id = int(q_num_match.group(1))

        # --- LOGIC TÁCH ĐÁP ÁN (SMART SPLIT) ---
        # Thay vì chỉ tìm "A.", ta tìm các Marker A, B, C, D nằm ở vị trí hợp lý
        # Regex này tìm: (Đầu dòng hoặc khoảng trắng) + (A hoặc [[A]]) + (dấu chấm hoặc đóng ngoặc)
        opt_pattern = r'(?:^|[\s])((?:\[\[([A-D])\]\]|([A-D]))[\.\)])'
        
        matches = list(re.finditer(opt_pattern, block))
        
        # Thuật toán: Tìm vị trí cắt sao cho hợp lý nhất
        # Nếu tìm thấy 4 marker A, B, C, D -> Cắt tại A
        # Nếu chỉ thấy A, B, C -> Cắt tại A
        
        split_idx = -1
        
        # Lọc các match để tìm chuỗi A -> B -> C...
        if matches:
            # Tìm match đầu tiên là 'A'
            first_a_idx = -1
            for i, m in enumerate(matches):
                char = m.group(2) or m.group(3) # Lấy chữ cái (đã bỏ [[]])
                if char == 'A':
                    first_a_idx = i
                    break
            
            if first_a_idx != -1:
                # Lấy index trong string của chữ A này
                split_idx = matches[first_a_idx].start(1) # start(1) là bắt đầu của nhóm A.
        
        # Tách Câu hỏi và Đáp án
        if split_idx != -1:
            q_part = block[:split_idx]
            opts_part = block[split_idx:]
        else:
            q_part = block
            opts_part = ""

        # --- CLEAN CÂU HỎI ---
        # Xóa chữ "Câu X:" ở đầu
        q_part = re.sub(r'^Câu\s+\d+[:\.]?\s*', '', q_part).strip()
        
        question_obj = {
            "id": q_id,
            "question": q_part,
            "options": [],
            "correct_answer_index": -1,
            "images": []
        }

        # --- PARSE OPTIONS ---
        if opts_part:
            # Tìm lại các marker trong phần opts_part để cắt chính xác nội dung
            markers = []
            for m in re.finditer(opt_pattern, opts_part):
                markers.append({
                    'full': m.group(1), 
                    'char': m.group(2) or m.group(3), 
                    'start': m.start(1), 
                    'end': m.end()
                })
            
            parsed_opts = {"A":"", "B":"", "C":"", "D":""}
            correct_char = None
            
            for i, m in enumerate(markers):
                char = m['char']
                # Check đúng (có [[ ]])
                if '[[' in m['full']: correct_char = char
                
                # Cắt text từ cuối marker này đến đầu marker kia
                start = m['end']
                end = markers[i+1]['start'] if i < len(markers)-1 else len(opts_part)
                
                content = opts_part[start:end].strip()
                # Xóa các ký tự thừa ở cuối nếu có
                parsed_opts[char] = content
            
            question_obj["options"] = [parsed_opts.get(k, "...") for k in "ABCD"]
            if correct_char: 
                question_obj["correct_answer_index"] = ord(correct_char) - ord('A')

        # Gán ảnh
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