"""FastAPI application for YouTube Transcript Downloader."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from docx import Document
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fpdf import FPDF
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_metadata import YouTubeMetadata

from transcript_utils import (
    build_filtered_text,
    estimate_file_size_bytes,
    extract_video_id,
    format_size,
    format_timestamp,
    parse_timecode,
    sanitize_filename,
)

BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "images" / "icon.png"

# Initialize FastAPI app
app = FastAPI(title="YouTube Transcript Downloader")

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/images", StaticFiles(directory=str(BASE_DIR / "images")), name="images")

# Setup Jinja2 templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# Pydantic models for request/response
class FetchRequest(BaseModel):
    url: str


class FetchResponse(BaseModel):
    video_id: str
    video_title: Optional[str]
    video_description: Optional[str]
    video_length: Optional[float]
    video_url: str
    thumbnail_url: Optional[str]
    transcript_languages: dict[str, str]
    default_language: str
    segments: list[dict]


class ApplyOptionsRequest(BaseModel):
    video_id: str
    language_code: str
    start_time: str
    end_time: str
    display_mode: str
    include_title: bool
    include_description: bool
    video_title: Optional[str]
    video_description: Optional[str]
    video_length: Optional[float] = None
    segments: list[dict]


class ApplyOptionsResponse(BaseModel):
    text: str
    word_count: int
    char_count: int
    size_bytes: int
    size_str: str


class ExportRequest(BaseModel):
    text: str
    filename: str
    format: str


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the main page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/fetch", response_model=FetchResponse)
async def fetch_transcript(request: FetchRequest):
    """Fetch video metadata and transcript."""
    video_id = extract_video_id(request.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract video ID from URL")

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    # Fetch video metadata
    video_title = None
    video_description = None
    video_length = None
    thumbnail_url = None

    try:
        print(f"[fetch_transcript] Fetching metadata for URL: {request.url}")
        yt = YouTubeMetadata(request.url)
        video_title = yt.title
        video_description = yt.description
        video_length = yt.length or 0.0
        if video_length <= 0:
            video_length = None
        thumbnail_url = yt.thumbnail_url

        print(f"[fetch_transcript] Metadata fetched - Title: {video_title}, Length: {video_length}")

        if video_title is None:
            print(f"[fetch_transcript] WARNING: Title is None after YouTubeMetadata fetch")
    except Exception as e:
        print(f"[fetch_transcript] ERROR: Exception while fetching video info: {e}")
        import traceback
        traceback.print_exc()

    # Fetch transcript options (languages) and default transcript
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        # Build language options (deduplicated by language_code)
        lang_options: dict[str, str] = {}
        default_code: Optional[str] = None

        for t in transcript_list:
            code = t.language_code
            label = t.language

            if t.is_generated:
                label += " (auto-generated)"

            label_with_code = f"{label} [{code}]"

            # Deduplicate by language_code
            if code not in lang_options:
                lang_options[code] = label_with_code

            # First transcript as fallback default
            if default_code is None:
                default_code = code
            # Prefer English if present
            if code.startswith("en"):
                default_code = code

        if not lang_options:
            raise RuntimeError("No transcripts available")

        # Choose default language code
        if default_code is None:
            default_code = next(iter(lang_options.keys()))

        # Load the default transcript
        transcript = transcript_list.find_transcript([default_code])
        fetched = transcript.fetch()

        # Normalize to list[dict]
        segments: list[dict] = []
        if hasattr(fetched, "to_raw_data"):
            segments = fetched.to_raw_data()
        else:
            for snippet in fetched:
                if hasattr(snippet, "to_dict"):
                    seg_dict = snippet.to_dict()
                else:
                    seg_dict = {
                        "text": getattr(snippet, "text", ""),
                        "start": float(getattr(snippet, "start", 0.0)),
                        "duration": float(getattr(snippet, "duration", 0.0)),
                    }
                segments.append(seg_dict)

        if not segments:
            raise RuntimeError("Could not load default transcript")

    except Exception as e:
        print(f"[fetch_transcript] Error: {e}")
        raise HTTPException(
            status_code=400,
            detail="Error fetching transcript: the video has no accessible transcripts or is unavailable."
        )

    return FetchResponse(
        video_id=video_id,
        video_title=video_title,
        video_description=video_description,
        video_length=video_length,
        video_url=video_url,
        thumbnail_url=thumbnail_url,
        transcript_languages=lang_options,
        default_language=default_code,
        segments=segments,
    )


@app.post("/api/load_transcript")
async def load_transcript(video_id: str, language_code: str):
    """Load transcript for a specific language."""
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        transcript = transcript_list.find_transcript([language_code])
        fetched = transcript.fetch()

        # Normalize to list[dict]
        segments: list[dict] = []
        if hasattr(fetched, "to_raw_data"):
            segments = fetched.to_raw_data()
        else:
            for snippet in fetched:
                if hasattr(snippet, "to_dict"):
                    seg_dict = snippet.to_dict()
                else:
                    seg_dict = {
                        "text": getattr(snippet, "text", ""),
                        "start": float(getattr(snippet, "start", 0.0)),
                        "duration": float(getattr(snippet, "duration", 0.0)),
                    }
                segments.append(seg_dict)

        return JSONResponse(content={"segments": segments})

    except Exception as e:
        print(f"[load_transcript] Error: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Could not load transcript for language '{language_code}'"
        )


def validate_time_range(
    start_str: str,
    end_str: str,
    video_length: Optional[float],
    segments: list[dict]
) -> tuple[str, str]:
    """
    Validate and normalize start/end time range.

    Returns (normalized_start_str, normalized_end_str) if valid.
    Raises HTTPException if invalid.
    """
    # Determine video duration
    duration = video_length
    if duration is None or duration <= 0:
        if segments:
            last = segments[-1]
            duration = float(last["start"] + last.get("duration", 0))
        else:
            raise HTTPException(
                status_code=400,
                detail="Transcript not loaded; please fetch transcript first."
            )

    # Parse timestamps
    raw_start = (start_str or "").strip()
    raw_end = (end_str or "").strip()

    # Interpret combinations (empty means use defaults)
    if raw_start == "" and raw_end == "":
        start_sec = 0.0
        end_sec = float(duration)
    elif raw_start != "" and raw_end == "":
        start_sec = parse_timecode(raw_start)
        if start_sec is None:
            raise HTTPException(status_code=400, detail="Invalid start time format.")
        end_sec = float(duration)
    elif raw_start == "" and raw_end != "":
        end_sec = parse_timecode(raw_end)
        if end_sec is None:
            raise HTTPException(status_code=400, detail="Invalid end time format.")
        start_sec = 0.0
    else:
        start_sec = parse_timecode(raw_start)
        end_sec = parse_timecode(raw_end)
        if start_sec is None:
            raise HTTPException(status_code=400, detail="Invalid start time format.")
        if end_sec is None:
            raise HTTPException(status_code=400, detail="Invalid end time format.")

    # Clamp to [0, duration]
    start_sec = max(0.0, min(start_sec, duration))
    end_sec = max(0.0, min(end_sec, duration))

    # Enforce end > start
    if end_sec <= start_sec:
        raise HTTPException(
            status_code=400,
            detail="End time must be greater than start time."
        )

    # Return normalized values
    return format_timestamp(start_sec), format_timestamp(end_sec)


@app.post("/api/apply_options", response_model=ApplyOptionsResponse)
async def apply_options(request: ApplyOptionsRequest):
    """Apply transcript options and return formatted text."""
    # Validate time range
    normalized_start, normalized_end = validate_time_range(
        request.start_time,
        request.end_time,
        request.video_length,
        request.segments
    )

    text = build_filtered_text(
        segments=request.segments,
        start_str=normalized_start,
        end_str=normalized_end,
        display_mode=request.display_mode,
        include_title=request.include_title,
        include_description=request.include_description,
        video_title=request.video_title,
        video_description=request.video_description,
    )

    words = len(text.split())
    chars = len(text)
    size_bytes = estimate_file_size_bytes(text)

    return ApplyOptionsResponse(
        text=text,
        word_count=words,
        char_count=chars,
        size_bytes=size_bytes,
        size_str=format_size(size_bytes),
    )


@app.post("/api/export")
async def export_file(request: ExportRequest):
    """Export transcript in the requested format."""
    text = request.text
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to export")

    base_name = sanitize_filename(request.filename) if request.filename else "transcript"

    if request.format == "txt":
        data = text.encode("utf-8")
        filename = base_name + ".txt"
        media_type = "text/plain"

    elif request.format == "csv":
        lines = text.splitlines()
        output = io.StringIO()
        output.write("text\n")
        for line in lines:
            escaped = line.replace('"', '""')
            output.write(f'"{escaped}"\n')
        data = output.getvalue().encode("utf-8")
        filename = base_name + ".csv"
        media_type = "text/csv"

    elif request.format == "docx":
        doc = Document()
        for paragraph in text.split("\n\n"):
            doc.add_paragraph(paragraph)
        buf = io.BytesIO()
        doc.save(buf)
        data = buf.getvalue()
        filename = base_name + ".docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    elif request.format == "pdf":
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_margins(15, 15, 15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)

        line_height = pdf.font_size * 1.5
        effective_width = pdf.w - pdf.l_margin - pdf.r_margin

        cleaned_text = text.replace("\r\n", "\n").replace("\r", "\n")
        pdf.multi_cell(effective_width, line_height, cleaned_text)

        raw_pdf = pdf.output()
        if isinstance(raw_pdf, (bytes, bytearray)):
            data = bytes(raw_pdf)
        else:
            data = str(raw_pdf).encode("latin-1")

        filename = base_name + ".pdf"
        media_type = "application/pdf"

    else:
        raise HTTPException(status_code=400, detail="Unknown export type")

    return StreamingResponse(
        io.BytesIO(data),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
