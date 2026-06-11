"""
Video + Audio muxing endpoint.
Accepts video file + audio file → returns merged MP4 with audio track.
Uses ffmpeg: video stream copied (no re-encoding), audio encoded as AAC.
"""

import os
import uuid
import shutil
import subprocess
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

TEMP_DIR = Path("/tmp/mux-audio")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
MAX_AUDIO_SIZE = 20 * 1024 * 1024   # 20MB


@router.post("/mux-audio")
async def mux_audio(
    video: UploadFile = File(..., description="Video file (MP4, WebM)"),
    audio: UploadFile = File(..., description="Audio file (MP3, WAV, OGG, M4A)"),
    shortest: bool = True,
):
    """
    Merge audio track onto video file.
    - Video stream is COPIED (no quality loss, no re-encoding)
    - Audio is encoded as AAC 192k
    - Output duration = shortest of video/audio (if shortest=True)
    - Returns merged MP4 as streaming response
    """
    job_id = str(uuid.uuid4())[:8]
    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        video_ext = Path(video.filename or "video.mp4").suffix or ".mp4"
        audio_ext = Path(audio.filename or "audio.mp3").suffix or ".mp3"

        video_path = job_dir / f"input{video_ext}"
        audio_path = job_dir / f"audio{audio_ext}"
        output_path = job_dir / "output.mp4"

        # Write video with size check
        video_size = 0
        with open(video_path, "wb") as f:
            while chunk := await video.read(1024 * 1024):
                video_size += len(chunk)
                if video_size > MAX_VIDEO_SIZE:
                    raise HTTPException(413, f"Video too large (max {MAX_VIDEO_SIZE // 1024 // 1024}MB)")
                f.write(chunk)

        # Write audio with size check
        audio_size = 0
        with open(audio_path, "wb") as f:
            while chunk := await audio.read(1024 * 1024):
                audio_size += len(chunk)
                if audio_size > MAX_AUDIO_SIZE:
                    raise HTTPException(413, f"Audio too large (max {MAX_AUDIO_SIZE // 1024 // 1024}MB)")
                f.write(chunk)

        logger.info(f"[mux-audio:{job_id}] Video: {video_size/1024/1024:.1f}MB, Audio: {audio_size/1024/1024:.1f}MB")

        # ffmpeg: copy video stream, encode audio as AAC, web-optimized
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
        ]
        if shortest:
            cmd.append("-shortest")
        cmd.append(str(output_path))

        logger.info(f"[mux-audio:{job_id}] Running ffmpeg")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            logger.error(f"[mux-audio:{job_id}] ffmpeg stderr: {result.stderr[-500:]}")
            raise HTTPException(500, f"FFmpeg error: {result.stderr[-200:]}")

        if not output_path.exists():
            raise HTTPException(500, "FFmpeg produced no output")

        output_size = output_path.stat().st_size
        logger.info(f"[mux-audio:{job_id}] Output: {output_size/1024/1024:.1f}MB")

        def stream_file():
            try:
                with open(output_path, "rb") as f:
                    while chunk := f.read(1024 * 1024):
                        yield chunk
            finally:
                shutil.rmtree(job_dir, ignore_errors=True)

        return StreamingResponse(
            stream_file(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": 'attachment; filename="video-with-audio.mp4"',
                "Content-Length": str(output_size),
                "X-Job-Id": job_id,
            },
        )

    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except subprocess.TimeoutExpired:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(504, "FFmpeg timed out (max 2 minutes)")
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.error(f"[mux-audio:{job_id}] Error: {e}")
        raise HTTPException(500, str(e))
