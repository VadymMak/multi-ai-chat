"""
Image transformation endpoint.
Resize, compress, convert format, crop, and apply social media presets.
Uses Pillow — no AI, no external APIs, instant processing.
"""

import io
import logging
from enum import Enum
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

MAX_INPUT_SIZE = 50 * 1024 * 1024  # 50MB


class OutputFormat(str, Enum):
    jpeg = "jpeg"
    webp = "webp"
    png = "png"
    auto = "auto"


class Preset(str, Enum):
    instagram_square = "instagram_square"
    instagram_portrait = "instagram_portrait"
    instagram_story = "instagram_story"
    instagram_landscape = "instagram_landscape"
    tiktok = "tiktok"
    youtube_thumbnail = "youtube_thumbnail"
    youtube_banner = "youtube_banner"
    facebook_post = "facebook_post"
    facebook_cover = "facebook_cover"
    facebook_story = "facebook_story"
    twitter_post = "twitter_post"
    twitter_header = "twitter_header"
    linkedin_post = "linkedin_post"
    linkedin_cover = "linkedin_cover"
    pinterest = "pinterest"
    thumbnail = "thumbnail"
    og_image = "og_image"


PRESET_SIZES: dict[Preset, tuple[int, int]] = {
    Preset.instagram_square: (1080, 1080),
    Preset.instagram_portrait: (1080, 1350),
    Preset.instagram_story: (1080, 1920),
    Preset.instagram_landscape: (1080, 566),
    Preset.tiktok: (1080, 1920),
    Preset.youtube_thumbnail: (1280, 720),
    Preset.youtube_banner: (2560, 1440),
    Preset.facebook_post: (1200, 630),
    Preset.facebook_cover: (820, 312),
    Preset.facebook_story: (1080, 1920),
    Preset.twitter_post: (1200, 675),
    Preset.twitter_header: (1500, 500),
    Preset.linkedin_post: (1200, 627),
    Preset.linkedin_cover: (1584, 396),
    Preset.pinterest: (1000, 1500),
    Preset.thumbnail: (400, 400),
    Preset.og_image: (1200, 630),
}


def _smart_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    return ImageOps.fit(img, (target_w, target_h), method=Image.LANCZOS)


def _smart_resize(img: Image.Image, max_width: int, max_height: int) -> Image.Image:
    img.thumbnail((max_width, max_height), Image.LANCZOS)
    return img


def _pick_format(img: Image.Image, requested: OutputFormat) -> tuple[str, str, dict]:
    """Returns (format_name, mime_type, save_kwargs)."""
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    )

    if requested == OutputFormat.auto:
        if has_alpha:
            return "PNG", "image/png", {}
        return "WEBP", "image/webp", {"quality": 85, "method": 6}

    if requested == OutputFormat.jpeg:
        return "JPEG", "image/jpeg", {"quality": 85, "optimize": True}

    if requested == OutputFormat.webp:
        return "WEBP", "image/webp", {"quality": 85, "method": 6}

    if requested == OutputFormat.png:
        return "PNG", "image/png", {"optimize": True}

    return "WEBP", "image/webp", {"quality": 85, "method": 6}


def _to_rgb_for_jpeg(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white background for JPEG output."""
    if img.mode not in ("RGBA", "LA", "PA", "P"):
        return img
    if img.mode == "P":
        img = img.convert("RGBA")
    background = Image.new("RGB", img.size, (255, 255, 255))
    background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
    return background


@router.post("/transform-image")
async def transform_image(
    image: UploadFile = File(..., description="Input image file"),
    preset: Optional[Preset] = Form(None, description="Social media preset"),
    width: Optional[int] = Form(None, description="Target width in pixels"),
    height: Optional[int] = Form(None, description="Target height in pixels"),
    quality: Optional[int] = Form(None, description="Output quality 1-100 (default: 85)"),
    format: OutputFormat = Form(OutputFormat.auto, description="Output format"),
    crop: bool = Form(False, description="Crop to exact dimensions (True) or fit within (False)"),
):
    """
    Transform an image: resize, compress, convert, crop, or apply social media preset.

    Modes:
    - preset: Apply social media preset (e.g. instagram_square → 1080x1080 crop)
    - width + height + crop=True: Crop to exact dimensions
    - width + height + crop=False: Fit within dimensions (preserve aspect ratio)
    - width only / height only: Resize with proportional other dimension
    - No size params: Compress/convert only
    """
    data = await image.read()
    if len(data) > MAX_INPUT_SIZE:
        raise HTTPException(413, f"Image too large (max {MAX_INPUT_SIZE // 1024 // 1024}MB)")

    try:
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise HTTPException(400, "Invalid image file")

    img = ImageOps.exif_transpose(img) or img

    original_w, original_h = img.size
    logger.info(f"[transform] Input: {original_w}x{original_h} {len(data) / 1024:.0f}KB mode={img.mode}")

    if preset:
        target_w, target_h = PRESET_SIZES[preset]
        img = _smart_crop(img, target_w, target_h)
        logger.info(f"[transform] Preset {preset.value}: {target_w}x{target_h}")

    elif width or height:
        target_w = width or int(original_w * (height / original_h))
        target_h = height or int(original_h * (width / original_w))

        if crop:
            img = _smart_crop(img, target_w, target_h)
            logger.info(f"[transform] Crop: {target_w}x{target_h}")
        else:
            img = _smart_resize(img, target_w, target_h)
            logger.info(f"[transform] Resize: {img.size[0]}x{img.size[1]}")

    fmt_name, mime_type, save_kwargs = _pick_format(img, format)

    if quality is not None:
        quality = max(1, min(100, quality))
        if fmt_name in ("JPEG", "WEBP"):
            save_kwargs["quality"] = quality

    if fmt_name == "JPEG":
        img = _to_rgb_for_jpeg(img)

    buffer = io.BytesIO()
    img.save(buffer, format=fmt_name, **save_kwargs)
    buffer.seek(0)

    output_size = buffer.getbuffer().nbytes
    final_w, final_h = img.size
    logger.info(f"[transform] Output: {final_w}x{final_h} {output_size / 1024:.0f}KB {fmt_name}")

    base_name = (image.filename or "image").rsplit(".", 1)[0]
    ext = fmt_name.lower()
    if preset:
        out_filename = f"{base_name}_{preset.value}.{ext}"
    elif width or height:
        out_filename = f"{base_name}_{final_w}x{final_h}.{ext}"
    else:
        out_filename = f"{base_name}_optimized.{ext}"

    return StreamingResponse(
        buffer,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{out_filename}"',
            "Content-Length": str(output_size),
            "X-Original-Size": str(len(data)),
            "X-Output-Size": str(output_size),
            "X-Dimensions": f"{final_w}x{final_h}",
            "X-Compression-Ratio": f"{len(data) / max(output_size, 1):.1f}x",
        },
    )


@router.get("/transform-image/presets")
async def list_presets():
    """List all available social media presets with dimensions."""
    return {
        preset.value: {
            "width": size[0],
            "height": size[1],
            "aspect_ratio": f"{size[0]}:{size[1]}",
        }
        for preset, size in PRESET_SIZES.items()
    }
