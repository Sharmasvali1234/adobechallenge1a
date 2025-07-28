import fitz  # PyMuPDF
import pytesseract
import pandas as pd
from PIL import Image
import io
import os
import json
import re
from collections import Counter, namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configuration ---
INPUT_DIR = '/app/input'
OUTPUT_DIR = '/app/output'
TEXT_LENGTH_THRESHOLD = 150
OCR_DPI = 300

# --- Data Structure ---
TextBlock = namedtuple('TextBlock', ['text', 'size', 'font', 'bbox', 'page', 'dir'])

def clean_text(text):
    """Normalizes whitespace in a string."""
    return re.sub(r'\s+', ' ', text).strip()

def filter_non_content(blocks, doc):
    """
    Filters out watermarks while protecting the main title.
    """
    if not blocks:
        return []
        
    texts_to_remove = set()
    protected_texts = set()

    # Protect the most likely title on the first page
    first_page_blocks = [b for b in blocks if b.page == 0]
    if first_page_blocks:
        max_size = max(b.size for b in first_page_blocks)
        for b in first_page_blocks:
            if b.size == max_size:
                protected_texts.add(b.text)

    for block in blocks:
        if block.text in protected_texts:
            continue
        if block.dir and abs(block.dir[0]) < 0.99:
            texts_to_remove.add(block.text)

    if texts_to_remove:
        return [b for b in blocks if b.text not in texts_to_remove]
    
    return blocks

def parse_text_page(page_tuple):
    """
    Extracts structured text blocks from a single PDF page into TextBlock objects.
    """
    doc, page_num = page_tuple
    page = doc.load_page(page_num)
    blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_SEARCH)["blocks"]
    processed_blocks = []
    for block in blocks:
        if block['type'] == 0:  # Text block
            for line in block['lines']:
                line_text = ' '.join([span['text'] for span in line['spans']])
                line_text = clean_text(line_text)
                if not line_text: continue
                
                first_span = line['spans'][0]
                processed_blocks.append(TextBlock(
                    text=line_text, size=round(first_span['size']),
                    font=first_span['font'], bbox=line['bbox'], page=page.number,
                    dir=line['dir']
                ))
    return processed_blocks

def parse_image_page_with_ocr(page_tuple):
    """
    Extracts text from an image-based PDF page using OCR into TextBlock objects.
    """
    doc, page_num = page_tuple
    page = doc.load_page(page_num)
    pix = page.get_pixmap(dpi=OCR_DPI)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    
    ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DATAFRAME)
    
    ocr_data.dropna(subset=['text'], inplace=True)
    ocr_data = ocr_data[ocr_data.conf > 50]
    ocr_data['text'] = ocr_data['text'].astype(str).str.strip()
    ocr_data = ocr_data[ocr_data.text != '']

    processed_blocks = []
    if not ocr_data.empty:
        for _, line_df in ocr_data.groupby(['block_num', 'par_num', 'line_num']):
            line_text = clean_text(' '.join(line_df['text']))
            if not line_text: continue

            x0, y0 = line_df['left'].min(), line_df['top'].min()
            x1 = (line_df['left'] + line_df['width']).max()
            y1 = (line_df['top'] + line_df['height']).max()
            size_proxy = round(line_df['height'].mean())
            
            processed_blocks.append(TextBlock(
                text=line_text, size=size_proxy, font='OCR-Font',
                bbox=(x0, y0, x1, y1), page=page.number, dir=None
            ))
    return processed_blocks

def get_document_blocks_parallel(doc):
    """Processes all pages in a document in parallel to speed up text extraction."""
    all_blocks = []
    tasks = []
    for i in range(len(doc)):
        page = doc.load_page(i)
        if len(page.get_text().strip()) > TEXT_LENGTH_THRESHOLD:
            tasks.append(((doc, i), parse_text_page))
        else:
            tasks.append(((doc, i), parse_image_page_with_ocr))

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = [executor.submit(func, arg) for arg, func in tasks]
        for future in as_completed(futures):
            all_blocks.extend(future.result())
            
    all_blocks.sort(key=lambda b: (b.page, b.bbox[1]))
    return all_blocks

def classify_headings(doc, blocks):
    """Classifies blocks into a title and outline using an adaptive strategy."""
    if not blocks:
        return {"title": "Title Not Found", "outline": []}

    # --- Step 1: Document Type Detection ---
    is_graphical_doc = False
    if len(doc) == 1:
        paragraph_blocks = [b for b in blocks if len(b.text.split()) > 15]
        if len(blocks) < 40 and (not paragraph_blocks or len(paragraph_blocks) / len(blocks) < 0.1):
            is_graphical_doc = True

    if is_graphical_doc:
        largest_block = sorted(blocks, key=lambda x: x.size, reverse=True)[0]
        outline = [{"level": "H1", "text": clean_text(largest_block.text), "page": largest_block.page}]
        return {"title": "", "outline": outline}

    # --- Step 2: Handler for Standard and Structured Documents ---
    doc_title = "Title Not Found"
    title_parts = []
    first_page_blocks = [b for b in blocks if b.page == 0]
    if first_page_blocks:
        max_size = max(b.size for b in first_page_blocks)
        title_blocks = sorted([b for b in first_page_blocks if b.size == max_size], key=lambda b: b.bbox[1])
        title_parts = [b.text for b in title_blocks]
        doc_title = " ".join(title_parts)
    
    outline = []
    unique_sizes = sorted(list(set(b.size for b in blocks)), reverse=True)
    
    date_pattern = re.compile(
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}\b'
        r'|\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b',
        re.IGNORECASE
    )

    # Strategy 1: For structured docs like resumes and flyers
    if 1 < len(unique_sizes) <= 6:
        size_to_level = {size: f"H{i+1}" for i, size in enumerate(unique_sizes[:3])}
        for b in blocks:
            if b.text in title_parts or b.size not in size_to_level or date_pattern.match(b.text.strip()):
                continue
            
            text_to_add = b.text
            if len(text_to_add.split()) >= 10 and ':' in text_to_add:
                potential_heading = text_to_add.split(':', 1)[0]
                if len(potential_heading.split()) < 5:
                    text_to_add = potential_heading + ':'
            
            if len(text_to_add.split()) < 10:
                outline.append({"level": size_to_level[b.size], "text": text_to_add, "page": b.page})
    
    # Strategy 2: For standard text documents (reports, articles)
    else:
        para_sizes = [b.size for b in blocks if len(b.text.split()) > 20]
        body_size = Counter(para_sizes).most_common(1)[0][0] if para_sizes else (unique_sizes[-1] if unique_sizes else 0)

        heading_candidates = [b for b in blocks if b.text not in title_parts and b.size > body_size and len(b.text.split()) < 20 and not date_pattern.match(b.text.strip())]
        
        heading_sizes = sorted(list(set(b.size for b in heading_candidates)), reverse=True)
        size_to_level = {size: f"H{i+1}" for i, size in enumerate(heading_sizes[:3])}
        number_pattern = re.compile(r'^\s*([A-Z]|\d{1,2}(\.\d{1,2})*)\.?\s+')
        for b in sorted(heading_candidates, key=lambda b: (b.page, b.bbox[1])):
            level = size_to_level.get(b.size)
            match = number_pattern.match(b.text)
            if match: level = f"H{min(match.group(1).count('.') + 1, 3)}"
            if level: outline.append({"level": level, "text": b.text, "page": b.page})
            
    # --- Step 3: Final Cleanup ---
    final_outline = []
    seen = set()
    for item in outline:
        identifier = (item['text'], item['page'])
        if identifier not in seen:
            seen.add(identifier)
            final_outline.append(item)
            
    merged_outline = []
    if final_outline:
        merged_outline.append(final_outline[0])
        for i in range(1, len(final_outline)):
            prev_item = merged_outline[-1]
            current_item = final_outline[i]
            if (current_item['page'] == prev_item['page'] and
                current_item['level'] == prev_item['level'] and
                current_item['text'].strip().startswith('&')):
                prev_item['text'] = f"{prev_item['text']} {current_item['text']}"
            else:
                merged_outline.append(current_item)
    
    return {"title": clean_text(doc_title), "outline": merged_outline}

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    if not os.path.isdir(INPUT_DIR):
        exit(1)

    pdf_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".pdf")]
    
    if not pdf_files:
        exit(1)

    for filename in pdf_files:
        input_path = os.path.join(INPUT_DIR, filename)
        output_filename = f"{os.path.splitext(filename)[0]}.json"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        try:
            doc = fitz.open(input_path)
            if len(doc) > 50:
                error_result = {"error": "PDF exceeds 50-page limit", "title": "", "outline": []}
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(error_result, f, indent=2)
                doc.close()
                continue
                
            all_blocks = get_document_blocks_parallel(doc)
            filtered_blocks = filter_non_content(all_blocks, doc)
            result = classify_headings(doc, filtered_blocks)
            doc.close()
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

        except Exception as e:
            error_result = {"error": str(e), "title": "", "outline": []}
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(error_result, f, indent=2)