from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from typing import Optional
import os
import io
import pandas as pd
import fitz  # PyMuPDF
import docx
from PIL import Image
import pytesseract

from app.memory.manager import MemoryManager
from app.providers.claude_provider import ask_claude
from app.memory.db import get_db

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

router = APIRouter()

# ----------------------------- Text Extraction Helpers -----------------------------

def extract_text_by_type(file: UploadFile, content: bytes, ext: str) -> str:
    try:
        match ext:
            case ".txt" | ".md":
                return content.decode("utf-8", errors="ignore").replace("\r\n", "\n").strip()
            case ".csv":
                file.file.seek(0)
                return pd.read_csv(file.file).head(10).to_string()
            case ".xlsx":
                file.file.seek(0)
                return pd.read_excel(file.file).head(10).to_string()
            case ".pdf":
                return extract_pdf_text(content)
            case ".docx":
                return extract_docx_text(file)
            case ".jpg" | ".jpeg" | ".png" | ".tif" | ".tiff":
                return extract_image_ocr(content)
            case _:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    except Exception as e:
        print("❌ Text extraction failed:", e)
        raise HTTPException(status_code=400, detail=f"Failed to extract text: {str(e)}")

def extract_pdf_text(data: bytes) -> str:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        text, ocr_text = "", ""

        for i, page in enumerate(doc):
            page_text = page.get_text().strip()
            text += page_text + "\n"
            print(f"📄 Page {i+1} text length: {len(page_text)}")

            if len(page_text) < 200:
                print(f"📷 Running OCR for Page {i+1}")
                pix = page.get_pixmap(dpi=300)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr_text += pytesseract.image_to_string(img) + "\n"

            if len(text + ocr_text) > 4000:
                print("⛔ Reached 4000 char limit. Stopping early.")
                break

        if not text.strip() and not ocr_text.strip():
            raise ValueError("No text extracted from PDF, including OCR.")

        if ocr_text.strip():
            text += (
                "\n\n📷 This document contains image(s) or diagrams. OCR was used to extract visible text.\n"
                + ocr_text.strip()
            )

        return text.strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF parsing failed: {str(e)}")

def extract_docx_text(file: UploadFile) -> str:
    try:
        file.file.seek(0)
        doc = docx.Document(file.file)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DOCX parsing failed: {str(e)}")

def extract_image_ocr(image_data: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(image_data))
        ocr_text = pytesseract.image_to_string(image)
        if not ocr_text.strip():
            raise ValueError("OCR could not extract any text.")
        return "📷 This document is an image. Text was extracted using OCR.\n\n" + ocr_text.strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OCR failed: {str(e)}")

# ----------------------------- Upload Endpoint -----------------------------

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    role_id: int = Query(...),
    project_id: int = Query(...),
    provider: Optional[str] = Query("claude"),  # ✅ Optional, defaults to Claude
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    ext = os.path.splitext(file.filename)[-1].lower()
    content = await file.read()
    print(f"📁 Received: {file.filename} ({ext}), size={len(content)} bytes")

    try:
        text = extract_text_by_type(file, content, ext)
        print(f"📝 Extracted text length: {len(text)}")

        if not text.strip() or len(text.split()) < 10:
            summary = "⚠️ Skipped summarization: document too short or lacks meaningful content."
        else:
            print("🧠 Sending to summarizer...")

            user_prompt = {
                "role": "user",
                "content": (
                    "You are a document summarizer. Please summarize the following content clearly and concisely, "
                    "and ignore all prior conversations or translation tasks.\n\n"
                    f"{text[:4000]}"
                )
            }

            summary = None
            if provider == "openai":
                from app.providers.openai_provider import ask_openai  # ✅ Local import
                summary = ask_openai(
                    messages=[user_prompt],
                    system="You only summarize the provided document. No translation or chat."
                )
            else:
                summary = ask_claude(
                    messages=[user_prompt],
                    model="claude-3-5-sonnet-20241022",
                    system="You are a helpful assistant. Your only task is to summarize uploaded documents. Do not translate.",
                    memory=[],
                )

            if not summary or "[Error" in summary:
                summary = "⚠️ Summary failed or Claude/OpenAI returned no useful output."

        print(f"✅ Summary preview: {summary[:250]}")

        memory = MemoryManager(db)
        memory.store_memory(project_id=project_id, role_id=role_id, summary=summary, raw_text=text)

        return {
            "filename": file.filename,
            "size": len(content),
            "preview": text[:1000] + ("..." if len(text) > 1000 else ""),
            "summary": summary,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Internal Upload Error:", e)
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

