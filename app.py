import streamlit as st
import re
import json
import io
import docx # python-docx
import pdfplumber

# --- PHẦN 1: HÀM XỬ LÝ LOGIC ---

def is_line_under_word(word_bbox, line_bbox):
    w_x0, w_top, w_x1, w_bottom = word_bbox
    l_x0, l_top, l_x1, l_bottom = line_bbox
    
    # 1. KIỂM TRA DỌC (Vertical):
    # Thay vì chỉ check dưới chân, ta check: Đường kẻ phải nằm thấp hơn "giữa bụng" chữ cái
    # và không thấp quá 12px so với chân chữ.
    word_center_y = (w_top + w_bottom) / 2
    
    # Điều kiện: Line nằm dưới tâm chữ VÀ cách chân chữ không quá 12 đơn vị
    if not (word_center_y < l_top < w_bottom + 12): 
        return False

    # 2. KIỂM TRA NGANG (Horizontal Overlap):
    # Tính đoạn giao nhau giữa từ và đường kẻ
    overlap_x0 = max(w_x0, l_x0)
    overlap_x1 = min(w_x1, l_x1)
    
    if overlap_x1 <= overlap_x0: # Không giao nhau
        return False
        
    overlap_len = overlap_x1 - overlap_x0
    
    # THAY ĐỔI QUAN TRỌNG:
    # Thay vì tính tỷ lệ %, ta chỉ cần đoạn giao nhau > 3 pixel.
    # Điều này giúp bắt được trường hợp từ là "A.CauHoiDai" nhưng gạch chân chỉ ở "A"
    if overlap_len > 3:
        return True
        
    return False

def extract_text_from_pdf(file):
    """
    Dùng pdfplumber đọc text và phát hiện gạch chân (Line/Rect)
    """
    debug_logs = [] # Lưu log để in ra màn hình nếu cần
    
    try:
        full_text = ""
        with pdfplumber.open(file) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # 1. Lấy danh sách Candidates (Lines/Rects)
                candidates = []
                
                # Lấy Lines (thường là gạch chân chuẩn)
                for line in page.lines:
                    # Chấp nhận line hơi nghiêng xíu hoặc dày xíu
                    if abs(line['bottom'] - line['top']) < 10: 
                         candidates.append((line['x0'], line['top'], line['x1'], line['bottom']))
                
                # Lấy Rects (nhiều PDF dùng hình chữ nhật mỏng làm gạch chân)
                for rect in page.rects:
                    if abs(rect['bottom'] - rect['top']) < 10: 
                        candidates.append((rect['x0'], rect['top'], rect['x1'], rect['bottom']))

                # 2. Extract Words
                words = page.extract_words(keep_blank_chars=True)
                words.sort(key=lambda w: (w['top'], w['x0']))
                
                page_output = ""
                current_top = 0
                if words: current_top = words[0]['top']

                for word in words:
                    text = word['text']
                    clean_text = text.strip()
                    
                    if not clean_text:
                        page_output += text
                        continue

                    # --- XỬ LÝ LATEX (Trường hợp file chứa code ẩn) ---
                    if 'underline' in text and ('$' in text or '\\' in text):
                         match = re.search(r'([A-D])', text)
                         if match:
                             text = f"[[{match.group(1)}]]"
                    
                    # --- XỬ LÝ HÌNH HỌC (GEOMETRIC) ---
                    # Logic: Nếu từ BẮT ĐẦU bằng A, B, C, D (ví dụ "A.", "A)", "A")
                    elif clean_text[0] in ['A', 'B', 'C', 'D'] and '[[' not in text:
                        
                        # Chỉ check các từ ngắn hoặc bắt đầu câu đáp án
                        # (Tránh check nhầm chữ cái giữa câu)
                        possible_option = clean_text[0] # Lấy A, B, C, D
                        
                        w_bbox = (word['x0'], word['top'], word['x1'], word['bottom'])
                        is_underlined = False
                        
                        for line_bbox in candidates:
                            if is_line_under_word(w_bbox, line_bbox):
                                is_underlined = True
                                # Ghi log debug cho trang đầu tiên để kiểm tra
                                if page_num == 0:
                                    debug_logs.append(f"Found underline for '{clean_text}': Word {w_bbox} vs Line {line_bbox}")
                                break
                        
                        if is_underlined:
                            # Thay thế ký tự đầu tiên. Ví dụ "A." -> "[[A]]."
                            text = text.replace(possible_option, f"[[{possible_option}]]", 1)
                        else:
                            # Log những thằng KHÔNG tìm thấy để debug
                            if page_num == 0 and clean_text in ['A.', 'B.', 'C.', 'D.']:
                                debug_logs.append(f"MISSED '{clean_text}': Word {w_bbox}. Nearest line distance too far?")

                    # Logic ghép câu
                    if abs(word['top'] - current_top) > 8: 
                        page_output += "\n"
                        current_top = word['top']
                    elif page_output and not page_output.endswith(('\n', ' ')):
                        page_output += " "
                        
                    page_output += text
                    
                full_text += page_output + "\n"
        
        return full_text, debug_logs
    except Exception as e:
        import traceback
        return f"Error: {str(e)}\n{traceback.format_exc()}", []

def extract_text_from_docx(file):
    try:
        doc = docx.Document(file)
        full_text = []
        for para in doc.paragraphs:
            para_text = ""
            for run in para.runs:
                text = run.text
                # Check Bold hoặc Underline
                if run.underline or run.bold: 
                    # Regex bắt "A" hoặc "A." hoặc "A)"
                    if re.match(r'^\s*[A-D][\.\)]?\s*$', text) or re.match(r'^\s*[A-D]\s*$', text):
                         char = text.strip()[0] # Lấy A
                         rest = text.strip()[1:] # Lấy phần còn lại (. )
                         text = f"[[{char}]]{rest}"
                para_text += text
            full_text.append(para_text)
        return "\n".join(full_text)
    except Exception as e:
        return f"Error: {str(e)}"
    
def parse_quiz_content(raw_text):
    # 1. CLEANING
    text = re.sub(r'\'', '', raw_text)
    # Fix lỗi latex gạch chân
    text = re.sub(r'\$\\underline\s*\{?\s*([A-D])\s*\}?\$', r'[[\1]]', text) 
    
    # 2. SPLITTING
    raw_questions = re.split(r'(?:\n|^)(?=Câu\s+\d+[:\.])', text)
    
    quiz_data = []

    for block in raw_questions:
        block = block.strip()
        if not block or not re.match(r'Câu\s+\d+', block):
            continue
            
        question_obj = {
            "question": "",
            "options": [],
            "correct_answer_index": -1
        }
        
        # --- BƯỚC 1: TÌM "MỎ NEO" A (ANCHOR A) ---
        # Tìm chữ A. hoặc [[A]]. hoặc A) nằm ở đầu dòng hoặc sau khoảng trắng
        # Group 1: [[A]], Group 2: A
        pattern_A = r'(?:^|\s|\n)(?:\[\[(A)\]\]|(A))[\.\)]'
        match_A = re.search(pattern_A, block)
        
        if match_A:
            # --- TÁCH CÂU HỎI ---
            # Cắt từ đầu đến vị trí tìm thấy A
            split_idx = match_A.start()
            
            # Phần câu hỏi là phần trước A -> An toàn tuyệt đối, không sợ B) trong ngoặc
            q_part = block[:split_idx].strip()
            # Phần đáp án là phần từ A trở về sau
            opts_part = block[split_idx:].strip()
            
        else:
            # Fallback: Nếu không tìm thấy A (đề lỗi hoặc format lạ), coi như cả cục là câu hỏi
            q_part = block
            opts_part = ""

        # Clean text câu hỏi
        q_part = re.sub(r'^Câu\s+\d+[:\.]\s*', '', q_part)
        question_obj["question"] = q_part.strip()
        
        # --- BƯỚC 2: XỬ LÝ VÙNG ĐÁP ÁN (SLICING) ---
        # Thay vì split, ta dùng finditer để tìm vị trí các mốc A, B, C, D
        if opts_part:
            # Regex tìm tất cả các marker A, B, C, D trong vùng opts_part
            # Pattern: (Start/Space/Newline) + ([[Char]] or Char) + (Dot/Paren)
            marker_pattern = r'(?:^|\s|\n)(?:\[\[([A-D])\]\]|([A-D]))[\.\)]'
            
            matches = list(re.finditer(marker_pattern, opts_part))
            
            # Logic ghép nội dung dựa trên vị trí (Slicing)
            # Ví dụ: Nội dung A là từ marker A đến marker B (hoặc hết chuỗi)
            
            parsed_options = {"A": "", "B": "", "C": "", "D": ""}
            correct_char = None
            
            for i, match in enumerate(matches):
                # Xác định nhãn (A, B, C hay D)
                label_underline = match.group(1) # Nếu là [[A]]
                label_normal = match.group(2)    # Nếu là A
                label = label_underline if label_underline else label_normal
                
                if label_underline:
                    correct_char = label_underline

                # Lấy vị trí bắt đầu nội dung (sau marker)
                start_content = match.end()
                
                # Lấy vị trí kết thúc nội dung (là vị trí bắt đầu của marker tiếp theo)
                if i < len(matches) - 1:
                    end_content = matches[i+1].start()
                    content = opts_part[start_content:end_content].strip()
                else:
                    # Marker cuối cùng (thường là D) -> lấy đến hết chuỗi
                    content = opts_part[start_content:].strip()
                
                # Lưu vào map
                parsed_options[label] = content

            # Chuyển sang list
            final_options = [parsed_options.get(k, "") for k in ['A', 'B', 'C', 'D']]
            question_obj["options"] = final_options
            
            if correct_char:
                 question_obj["correct_answer_index"] = ord(correct_char) - ord('A')

        if question_obj["question"]:
            quiz_data.append(question_obj)
            
    return quiz_data

# def parse_quiz_content(raw_text):
#     # 1. CLEANING
#     text = re.sub(r'\'', '', raw_text)
#     # Fix lỗi latex gạch chân
#     text = re.sub(r'\$\\underline\s*\{?\s*([A-D])\s*\}?\$', r'[[\1]]', text) 
    
#     # 2. SPLITTING
#     # Tách các block câu hỏi
#     raw_questions = re.split(r'(?:\n|^)(?=Câu\s+\d+[:\.])', text)
    
#     quiz_data = []

#     for block in raw_questions:
#         block = block.strip()
#         if not block or not re.match(r'Câu\s+\d+', block):
#             continue
            
#         question_obj = {
#             "question": "",
#             "options": [],
#             "correct_answer_index": -1
#         }
        
#         # --- CHIẾN THUẬT MỚI: TÌM ĐIỂM CẮT TẠI ĐÁP ÁN A ---
        
#         # Regex tìm đáp án A (hoặc [[A]]). 
#         # Yêu cầu: Phải nằm ở đầu dòng (newline) HOẶC cách xa chữ trước đó (>2 spaces)
#         # Điều này giúp tránh nhận nhầm chữ A trong câu hỏi.
#         pattern_A = r'(?:^|\n|\s{2,})(?:\[\[A\]\]|A)[\.\)]\s'
        
#         match_A = re.search(pattern_A, block)
        
#         options_block = ""
        
#         if match_A:
#             # Nếu tìm thấy A -> Cắt đôi block
#             split_index = match_A.start()
            
#             # Phần 1: Câu hỏi (Từ đầu đến trước chữ A)
#             q_text = block[:split_index].strip()
            
#             # Phần 2: Chuỗi chứa các đáp án (Từ chữ A trở đi)
#             options_block = block[split_index:].strip()
            
#         else:
#             # Fallback: Nếu không thấy A (đề lỗi), dùng regex tìm bất kỳ đáp án nào đầu dòng
#             # (Logic cũ nhưng an toàn hơn chút)
#             parts = re.split(r'(?:^|\n)(?:\[\[([A-D])\]\]|([A-D]))[\.\)]\s+', block, maxsplit=1)
#             q_text = parts[0].strip()
#             if len(parts) > 1:
#                 # Tái tạo lại phần option đã bị split cắt mất
#                 options_block = block[len(parts[0]):].strip()

#         # Clean text câu hỏi
#         q_text = re.sub(r'^Câu\s+\d+[:\.]\s*', '', q_text)
#         question_obj["question"] = q_text
        
#         # --- XỬ LÝ OPTIONS TỪ KHỐI OPTIONS_BLOCK ---
#         # Lúc này options_block chỉ chứa "A. ... B. ...", không còn dính câu hỏi.
#         # Nên ta có thể dùng Regex mạnh tay để bắt B, C, D nằm cùng dòng (Horizontal).
        
#         if options_block:
#             # Regex: Tìm A, B, C, D kèm dấu chấm/ngoặc, phía trước có thể là khoảng trắng hoặc xuống dòng
#             # Group 1: [[A]]
#             # Group 2: A
#             opt_parts = re.split(r'(?:^|\n|\s+)(?:\[\[([A-D])\]\]|([A-D]))[\.\)]\s+', options_block)
            
#             current_options_map = {}
#             # opt_parts[0] thường là rỗng vì options_block bắt đầu bằng A
            
#             i = 1
#             while i < len(opt_parts) - 1:
#                 label_correct = opt_parts[i]
#                 label_normal = opt_parts[i+1]
#                 content = opt_parts[i+2].strip() if (i+2) < len(opt_parts) else ""
                
#                 label = label_correct if label_correct else label_normal
                
#                 if label:
#                     current_options_map[label] = content
#                     if label_correct:
#                         question_obj["correct_answer_index"] = ord(label_correct) - ord('A')
                
#                 i += 3

#             final_options = []
#             for char in ['A', 'B', 'C', 'D']:
#                 final_options.append(current_options_map.get(char, ""))
                
#             question_obj["options"] = final_options
        
#         if question_obj["question"]:
#             quiz_data.append(question_obj)
            
#     return quiz_data

# --- PHẦN 2: UI STREAMLIT ---

st.set_page_config(page_title="Quiz Converter Pro", layout="wide")
st.title("📄 Tool Chuyển Đổi Đề Thi (Fix v3: Aggressive Detection)")

st.markdown(r"""
**Hướng dẫn:**
* **PDF:** Tool sẽ quét toạ độ để tìm gạch chân. Nếu không tìm thấy, hãy xem mục **"Technical Logs"** bên dưới để biết lý do (khoảng cách quá xa hay không khớp toạ độ).
""")

col1, col2 = st.columns(2)

with col1:
    uploaded_file = st.file_uploader("Upload file đề thi", type=['docx', 'pdf', 'txt'])
    
    raw_text = ""
    debug_info = []
    
    if uploaded_file:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        
        with st.spinner('Đang xử lý...'):
            if file_ext == 'docx':
                raw_text = extract_text_from_docx(uploaded_file)
                st.success("Đã xử lý file Word.")
            elif file_ext == 'pdf':
                # Hàm trả về 2 giá trị: text và log
                raw_text, debug_info = extract_text_from_pdf(uploaded_file)
                st.success("Đã xử lý file PDF.")
            elif file_ext == 'txt':
                stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
                raw_text = stringio.read()

        # Debug Area 1: Text kết quả
        with st.expander("🔍 Kiểm tra Text (Tìm dấu [[A]])"):
            st.text(raw_text[:3000]) 
            
        # Debug Area 2: Logs toạ độ (Quan trọng để fix lỗi)
        if debug_info:
            with st.expander("🛠 Technical Logs (Toạ độ Word vs Line)"):
                for log in debug_info[:20]: # Chỉ hiện 20 log đầu
                    st.code(log, language='text')
                if len(debug_info) > 20:
                    st.text(f"... và {len(debug_info)-20} logs khác.")

    process = st.button("🚀 Chuyển đổi JSON", type="primary", disabled=not uploaded_file)

with col2:
    if process and raw_text:
        result = parse_quiz_content(raw_text)
        
        total = len(result)
        with_ans = sum(1 for q in result if q['correct_answer_index'] != -1)
        
        st.metric(label="Kết quả tìm kiếm", value=f"{with_ans}/{total} câu có đáp án")
        
        if total > 0 and with_ans == 0:
            st.error("⚠️ Vẫn chưa bắt được đáp án! Hãy mở mục 'Technical Logs' bên trái để xem toạ độ lệch bao nhiêu.")

        st.json(result, expanded=False)
        
        st.download_button(
            "📥 Tải JSON",
            data=json.dumps(result, ensure_ascii=False, indent=4),
            file_name="quiz_data.json",
            mime="application/json"
        )