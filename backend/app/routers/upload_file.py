# app/routers/upload_file.py
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, Union
from pathlib import Path  # ✅ ДОБАВЬ ЭТУ СТРОКУ
from datetime import datetime  # ✅ ДОБАВЬ ЭТУ СТРОКУ
import os
import io
from uuid import uuid4

# Optional deps (graceful fallbacks)
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # type: ignore

try:
    import fitz  # type: ignore  # PyMuPDF
except Exception:
    fitz = None  # type: ignore

try:
    import docx  # type: ignore  # python-docx
except Exception:
    docx = None  # type: ignore

try:
    from PIL import Image  # type: ignore
    import pytesseract # type: ignore
    HAS_OCR = True
except Exception:
    Image = None  # type: ignore
    pytesseract = None  # type: ignore
    HAS_OCR = False

from app.memory.manager import MemoryManager
from app.providers.claude_provider import ask_claude
from app.providers.openai_provider import ask_openai
from app.memory.db import get_db
from app.config.settings import settings
from app.memory.models import Attachment

import platform

# Tesseract path (override via env if needed)
if HAS_OCR and pytesseract:
    if platform.system() == "Windows":
        tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    else:
        tesseract_path = "/usr/bin/tesseract"  # Linux/Mac
    
    pytesseract.pytesseract.tesseract_cmd = os.getenv(
        "TESSERACT_CMD", 
        tesseract_path
    )

router = APIRouter(tags=["Upload"])

# Optional: choose a specific OpenAI model for summarization
OPENAI_SUMMARIZE_MODEL = getattr(settings, "OPENAI_SUMMARIZE_MODEL", None)

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

# Allowed file types
ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".csv", ".xlsx", ".pdf", ".docx",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff"
}

# ----------------------------- Text Extraction Helpers -----------------------------

def extract_text_by_type(file: UploadFile, content: bytes, ext: str) -> str:
    try:
        ext = (ext or "").lower()
        if ext in {".txt", ".md"}:
            return content.decode("utf-8", errors="ignore").replace("\r\n", "\n").strip()

        if ext == ".csv":
            if pd is None:
                raise HTTPException(status_code=400, detail="CSV parsing requires pandas. Please install pandas.")
            file.file.seek(0)
            return pd.read_csv(file.file).head(10).to_string()

        if ext == ".xlsx":
            if pd is None:
                raise HTTPException(status_code=400, detail="Excel parsing requires pandas. Please install pandas.")
            file.file.seek(0)
            return pd.read_excel(file.file).head(10).to_string()

        if ext == ".pdf":
            if fitz is None:
                raise HTTPException(status_code=400, detail="PDF parsing requires PyMuPDF (fitz). Please install pymupdf.")
            return extract_pdf_text(content)

        if ext == ".docx":
            if docx is None:
                raise HTTPException(status_code=400, detail="DOCX parsing requires python-docx. Please install python-docx.")
            return extract_docx_text(file)

        if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
            return extract_image_ocr(content)

        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    except HTTPException:
        raise
    except Exception as e:
        print("❌ Text extraction failed:", e)
        raise HTTPException(status_code=400, detail=f"Failed to extract text: {str(e)}")


def extract_pdf_text(data: bytes) -> str:
    try:
        doc = fitz.open(stream=data, filetype="pdf")  # type: ignore[attr-defined]
        text, ocr_text = "", ""

        for i, page in enumerate(doc):
            page_text = page.get_text().strip()
            text += page_text + "\n"
            print(f"📄 Page {i+1} text length: {len(page_text)}")

            # OCR if page is mostly non-text
            if len(page_text) < 200 and HAS_OCR:
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF parsing failed: {str(e)}")


def extract_docx_text(file: UploadFile) -> str:
    try:
        file.file.seek(0)
        doc = docx.Document(file.file)  # type: ignore[attr-defined]
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DOCX parsing failed: {str(e)}")


def extract_image_ocr(image_data: bytes) -> str:
    if not HAS_OCR:
        # Вместо ошибки, возвращаем базовое сообщение
        return "📷 Image uploaded. OCR is not available - install pytesseract to extract text from images."
    
    try:
        image = Image.open(io.BytesIO(image_data))
        ocr_text = pytesseract.image_to_string(image)
        if not ocr_text.strip():
            # Если текст не найден, всё равно сохраняем изображение
            return "📷 Image uploaded. No text detected in the image."
        return "📷 This document is an image. Text was extracted using OCR.\n\n" + ocr_text.strip()
    except Exception as e:
        # Логируем ошибку, но не падаем
        print(f"⚠️ OCR processing failed: {e}")
        return f"📷 Image uploaded. OCR processing failed: {str(e)}"
    
# ----------------------------- File Storage Helper ---------------------------

def save_uploaded_file(file: UploadFile, content: bytes) -> tuple[str, str]:
    """
    Save file to disk and return (relative_path, filename)
    
    Returns:
        tuple: (file_path, unique_filename)
    """
    try:
        # Generate unique filename
        ext = os.path.splitext(file.filename or "")[-1].lower()
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{timestamp}_{uuid4().hex[:8]}{ext}"
        
        # Save to uploads directory
        file_path = UPLOADS_DIR / unique_filename
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        print(f"💾 File saved: {file_path}")
        
        # Return relative path
        return str(file_path), unique_filename
        
    except Exception as e:
        print(f"❌ Failed to save file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")


# ----------------------------- Upload Endpoint -----------------------------

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    role_id: int = Query(...),
    project_id: Union[int, str] = Query(...),
    chat_session_id: Optional[str] = Query(None),
    provider: Optional[str] = Query("claude"),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    ext = os.path.splitext(file.filename)[-1].lower()
    
    # ✅ Validate file type
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type {ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    content = await file.read()
    print(f"📁 Received: {file.filename} ({ext}), size={len(content)} bytes")

    try:
        # ✅ Save file to disk
        file_path, unique_filename = save_uploaded_file(file, content)
        
        # Extract text
        text = extract_text_by_type(file, content, ext)
        print(f"📝 Extracted text length: {len(text)}")

        # Summarize
        summary = "⚠️ Skipped summarization: document too short or lacks meaningful content."
        if text.strip() and len(text.split()) >= 10:
            print("🧠 Sending to summarizer...")

            system_msg = {
                "role": "system",
                "content": "You only summarize the provided document. No translation or chat.",
            }
            user_prompt = {
                "role": "user",
                "content": (
                    "You are a document summarizer. Please summarize the following content clearly and concisely, "
                    "and ignore all prior conversations or translation tasks.\n\n"
                    f"{text[:4000]}"
                ),
            }

            prov = (provider or "claude").lower()
            if prov == "openai":
                summary = ask_openai(
                    messages=[user_prompt],
                    system_prompt=system_msg["content"],
                    model=(OPENAI_SUMMARIZE_MODEL or None)
                )
            else:
                summary = ask_claude([system_msg, user_prompt])

            if not summary or "[openai error]" in summary.lower() or "[claude error]" in summary.lower():
                summary = "⚠️ Summary failed or the provider returned no useful output."

        print(f"✅ Summary preview: {summary[:250]}")

        memory = MemoryManager(db)
        project_id_str = str(project_id)
        chat_session_id = chat_session_id or str(uuid4())

        # 💾 Store memory
        memory.store_memory(
            project_id=project_id_str,
            role_id=role_id,
            summary=summary,
            raw_text=text,
            chat_session_id=chat_session_id,
        )

        # 💬 Store chat message with file reference
        preview_msg = f"📎 Uploaded file: {file.filename}\n\n{summary}"
        message_entry = memory.store_chat_message(
            project_id=project_id_str,
            role_id=role_id,
            chat_session_id=chat_session_id,
            sender="system",
            text=preview_msg,
        )

        # ✅ Create attachment record
        mime_type = file.content_type or "application/octet-stream"
        file_type = "image" if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff"} else \
                    "data" if ext in {".csv", ".xlsx"} else "document"
        
        attachment = Attachment(
            message_id=message_entry.id,
            filename=unique_filename,
            original_filename=file.filename,
            file_type=file_type,
            mime_type=mime_type,
            file_size=len(content),
            file_path=file_path,
            uploaded_at=datetime.utcnow(),
        )
        
        db.add(attachment)
        db.commit()
        db.refresh(attachment)
        
        print(f"✅ Attachment saved: id={attachment.id}")

        # 🧾 Audit log
        memory.insert_audit_log(
            project_id=project_id_str,
            role_id=role_id,
            chat_session_id=chat_session_id,
            provider=("openai" if (provider or "").lower() == "openai" else "anthropic"),
            action="upload_file",
            query=f"file={file.filename}, size={len(content)}"[:300],
        )

        return {
            "filename": file.filename,
            "attachment_id": attachment.id,
            "size": len(content),
            "file_type": file_type,
            "download_url": f"/api/uploads/{attachment.id}",
            "preview": text[:500] + ("..." if len(text) > 500 else ""),
            "summary": summary,
            "chat_session_id": chat_session_id,
            "message_id": message_entry.id,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Internal Upload Error:", e)
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")
    
# ----------------------------- Download Endpoint -----------------------------

from fastapi.responses import FileResponse

@router.get("/uploads/{attachment_id}")
async def download_file(
    attachment_id: int,
    db: Session = Depends(get_db),
):
    """
    Download uploaded file by attachment ID
    """
    try:
        # Find attachment
        attachment = db.query(Attachment).filter(
            Attachment.id == attachment_id
        ).first()
        
        if not attachment:
            raise HTTPException(
                status_code=404,
                detail=f"Attachment {attachment_id} not found"
            )
        
        # Check if file exists
        file_path = Path(attachment.file_path)
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File not found on disk: {attachment.file_path}"
            )
        
        print(f"📥 Downloading: {attachment.original_filename} (id={attachment_id})")
        
        # Return file
        return FileResponse(
            path=str(file_path),
            filename=attachment.original_filename,
            media_type=attachment.mime_type,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Download error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to download file: {str(e)}"
        )
