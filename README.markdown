# PDF Outline Extractor

## Approach
This solution extracts structured outlines (title and headings: H1, H2, H3) from PDF files, producing a JSON output as specified in the hackathon requirements. Key features:
- **Hybrid Extraction**: Uses PyMuPDF for text-based PDFs and Tesseract OCR for image-based PDFs (when text length is below a threshold).
- **Parallel Processing**: Employs ThreadPoolExecutor to process pages concurrently, optimizing for the 10-second execution time constraint on 50-page PDFs.
- **Adaptive Heading Detection**: Implements two strategies:
  - For structured documents (e.g., resumes, flyers) with few font sizes, maps font sizes to heading levels (H1-H3).
  - For standard documents (e.g., reports), identifies headings based on font size relative to body text and numbering patterns.
- **Multilingual Support**: Leverages Tesseract OCR's language capabilities for multilingual PDFs, including Japanese.
- **Watermark Filtering**: Removes non-content text (e.g., watermarks) based on text orientation while protecting the title.
- **Error Handling**: Gracefully handles errors by outputting JSON with error messages, ensuring robustness.

## Libraries Used
- **PyMuPDF (1.23.6)**: For extracting text and metadata from PDFs.
- **Pytesseract (0.3.10)**: For OCR on image-based PDFs.
- **Pandas (2.0.3)**: For processing OCR data.
- **Pillow (10.0.0)**: For handling image data from PDFs.
- **Python Standard Libraries**: `os`, `json`, `re`, `collections`, `concurrent.futures`.

Total dependency size is under 200MB, meeting the model size constraint. All dependencies are installed offline within the Docker container.

## How to Build and Run
The solution is designed to run in a Docker container with no network access, as per the hackathon requirements.

### Build
```bash
docker build --platform linux/amd64 -t mysolutionname:somerandomidentifier .
```

### Run
```bash
docker run --rm -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output --network none mysolutionname:somerandomidentifier
```

### Input/Output
- **Input**: Place PDF files (up to 50 pages each) in the `./input` directory.
- **Output**: For each `filename.pdf`, a corresponding `filename.json` is generated in the `./output` directory in the format:
  ```json
  {
    "title": "Document Title",
    "outline": [
      { "level": "H1", "text": "Heading Text", "page": 1 },
      ...
    ]
  }
  ```
- If a PDF exceeds 50 pages or encounters an error, a JSON file with an error message is generated.

## Notes
- The solution is optimized for AMD64 architecture and runs on CPU with no GPU dependencies.
- It handles both text and image-based PDFs, with OCR triggered for pages with minimal text.
- The code is modular, reusable for Round 1B, and avoids hardcoding or file-specific logic.
- Tested to meet the 10-second execution time for 50-page PDFs on a system with 8 CPUs and 16 GB RAM.