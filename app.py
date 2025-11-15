from nicegui import ui
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
from fpdf import FPDF
from docx import Document

from urllib.parse import urlparse, parse_qs
from typing import Optional
from types import SimpleNamespace
import io


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from typical URL formats."""
    try:
        parsed = urlparse(url.strip())
        if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            qs = parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        if parsed.hostname in ("youtu.be",):
            return parsed.path.lstrip("/")
        # Fallback: if it looks like a bare 11-char ID
        if len(url.strip()) == 11:
            return url.strip()
    except Exception:
        return None
    return None


def parse_timecode(s: Optional[str]) -> Optional[float]:
    """Parse 'mm:ss' or 'hh:mm:ss' into seconds (float). Return None if empty/invalid."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        m, sec = parts
        return m * 60 + sec
    elif len(parts) == 3:
        h, m, sec = parts
        return h * 3600 + m * 60 + sec
    return None


def format_timestamp(seconds: float) -> str:
    """Format seconds as hh:mm:ss or mm:ss."""
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"


def estimate_file_size_bytes(text: str) -> int:
    """Approximate file size in bytes for UTF-8 encoded text."""
    return len(text.encode("utf-8"))


def format_size(bytes_count: int) -> str:
    if bytes_count < 1024:
        return f"{bytes_count} B"
    kb = bytes_count / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    return f"{mb:.2f} MB"


def build_filtered_text(
    segments,
    start_str: str,
    end_str: str,
    display_mode: str,
    include_title: bool,
    include_description: bool,
    video_title: Optional[str],
    video_description: Optional[str],
) -> str:
    """
    Apply time filtering, timestamp placement, and optional title/description.

    display_mode options:
      - "ts_newline"  -> [00:10] on its own line, then text
      - "ts_before"   -> [00:10] text
      - "ts_after"    -> text [00:10]
      - "no_ts_lines" -> text, line-breaks kept, no timestamps
      - "no_ts_block" -> one big block, no timestamps
    """
    if not segments:
        return ""

    start_sec = parse_timecode(start_str)
    end_sec = parse_timecode(end_str)

    idx_start = 0
    idx_end = len(segments) - 1

    # "closest previous timestamp" logic for start
    if start_sec is not None:
        for i, seg in enumerate(segments):
            if seg["start"] >= start_sec:
                idx_start = max(0, i - 1)
                break
        else:
            idx_start = max(0, len(segments) - 2)

    # "closest next timestamp" logic for end
    if end_sec is not None:
        last_idx = 0
        for i, seg in enumerate(segments):
            if seg["start"] <= end_sec:
                last_idx = i
        idx_end = min(len(segments) - 1, last_idx + 1)

    filtered = segments[idx_start : idx_end + 1]
    lines = []

    for seg in filtered:
        ts = format_timestamp(seg["start"])
        text = seg["text"].replace("\n", " ").strip()

        if display_mode == "ts_newline":
            line = f"[{ts}]\n{text}"
        elif display_mode == "ts_before":
            line = f"[{ts}] {text}"
        elif display_mode == "ts_after":
            line = f"{text} [{ts}]"
        else:
            # no_ts_lines / no_ts_block
            line = text

        lines.append(line)

    if display_mode == "no_ts_block":
        body = " ".join(lines)
    else:
        body = "\n".join(lines)

    header_parts = []
    if include_title and video_title:
        header_parts.append(video_title.strip())
    if include_description and video_description:
        header_parts.append(video_description.strip())

    if header_parts:
        header = "\n\n".join(header_parts)
        if body:
            return header + "\n\n" + body
        else:
            return header
    else:
        return body


@ui.page("/")
def main_page():
    # state container
    state = SimpleNamespace(
        full_segments=[],
        video_title=None,
        video_description=None,
        current_text="",
        video_length=None,  # seconds (float) from pytube or transcript
    )

    ui.markdown("## YouTube Transcript Exporter")

    with ui.card().style("max-width: 900px; margin: auto;"):
        url_input = ui.input("YouTube URL").props("clearable").style("width: 100%;")

        # FETCH row + FETCH-only status
        with ui.row().classes("items-center"):
            fetch_button = ui.button("Fetch transcript")
            fetch_status_label = ui.label("")

        # PROGRESS BAR for fetch
        with ui.row().classes("items-center gap-2"):
            progress = (
                ui.linear_progress(value=0, show_value=False, size="20px")
                .props("striped instant-feedback")
                .style("width: 300px;")
            )

            with progress:
                progress_label = (
                    ui.label("0%")
                    .classes("text-sm text-black absolute-center")
                    .bind_text_from(
                        progress, "value", backward=lambda v: f"{int(v*100)}%"
                    )
                )

        # ---------- OPTIONS UI ----------
        with ui.expansion("Options", icon="settings", value=True):
            with ui.row():
                start_input = ui.input("Start time").style("width: 200px;")
                end_input = ui.input("End time").style("width: 200px;")

            # Error message for time range (shown right below the inputs)
            range_error_label = ui.label("").style("font-size: 0.8rem; color: #d32f2f;")

            range_hint_label = ui.label(
                "After fetching a video, defaults are 0 to full length. "
            ).style("font-size: 0.8rem; color: gray;")

            with ui.row():
                display_mode = ui.select(
                    label="Transcript display style",
                    options={
                        "ts_newline": "Timestamp on its own line",
                        "ts_before": "Timestamp before text (same line)",
                        "ts_after": "Timestamp after text (same line)",
                        "no_ts_lines": "No timestamp, keep line breaks",
                        "no_ts_block": "No timestamp, single block of text",
                    },
                    value="ts_before",
                ).style("width: 400px;")

            include_title_checkbox = ui.checkbox(
                "Include YouTube title in output", value=True
            )
            include_description_checkbox = ui.checkbox(
                "Include YouTube description in output", value=False
            )

            file_title_input = ui.input(
                "Output file base name", value="transcript"
            ).style("width: 300px;")

        # "Apply options" right after Options, before preview
        with ui.row().classes("items-center"):
            apply_button = ui.button("Apply options")

        ui.separator()

        # COUNTS (progress is above, near fetch)
        counts_label = ui.label("Words: 0 | Characters: 0 | Est. size: 0 B")

        ui.label("Transcript preview (editable)").style("margin-top: 8px;")

        preview_area = (
            ui.textarea()
            .props("rows=10")
            .style("width: 100%; height: 260px; overflow-y: auto;")
        )

        with ui.row().classes("items-center"):
            copy_button = ui.button("Copy to clipboard")
            export_txt_button = ui.button("Download TXT")
            export_csv_button = ui.button("Download CSV")
            export_docx_button = ui.button("Download DOCX")
            export_pdf_button = ui.button("Download PDF")

        # JS handler to actually copy the textarea content in the browser
        copy_button.on(
            "click",
            js_handler=f"""
                () => {{
                    const el = getHtmlElement('{preview_area.id}');
                    if (!el) return;
                    const text = el.value || "";
                    if (navigator.clipboard && navigator.clipboard.writeText) {{
                        navigator.clipboard.writeText(text);
                    }} else {{
                        const ta = document.createElement('textarea');
                        ta.value = text;
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);
                    }}
                }}
            """,
        )

        action_status_label = ui.label("")

        # ---------- helpers ----------

        def set_progress(value: float) -> None:
            """Update progress bar and percentage label (0–1 -> 0–100%)."""
            value = max(0.0, min(1.0, float(value)))
            progress.value = value
            progress_label.text = f"{int(value * 100)}%"

        def reset_progress() -> None:
            set_progress(0.0)

        def refresh_counts() -> None:
            text = state.current_text or ""
            words = len(text.split())
            chars = len(text)
            size_bytes = estimate_file_size_bytes(text)
            counts_label.text = f"Words: {words} | Characters: {chars} | Est. size: {format_size(size_bytes)}"

        def get_video_duration() -> Optional[float]:
            """Return best-guess duration in seconds (video_length or from transcript)."""
            if state.video_length is not None:
                return float(state.video_length)
            if state.full_segments:
                last = state.full_segments[-1]
                return float(last["start"] + last.get("duration", 0))
            return None

        def reset_to_full_range() -> None:
            """Set start/end inputs to the full video range 0 → duration."""
            duration = get_video_duration()
            if not duration or duration <= 0:
                return
            start_input.value = "0"
            end_input.value = format_timestamp(duration)
            range_error_label.text = ""

        def on_start_blur(e) -> None:
            """
            When the start field loses focus:
            - If both start and end are empty -> reset to full range (0 → duration)
            - If only start is empty        -> set start = 0
            """
            duration = get_video_duration()
            if not duration or duration <= 0:
                return

            s = (start_input.value or "").strip()
            e_val = (end_input.value or "").strip()

            if s == "" and e_val == "":
                # both cleared: full range
                reset_to_full_range()
            elif s == "":
                # only start cleared: default to 0
                start_input.value = "0"
                range_error_label.text = ""

        def on_end_blur(e) -> None:
            """
            When the end field loses focus:
            - If end is empty (regardless of start) -> reset BOTH to full range 0 → duration
            """
            duration = get_video_duration()
            if not duration or duration <= 0:
                return

            e_val = (end_input.value or "").strip()
            if e_val == "":
                # any time end is cleared, snap both to full range
                reset_to_full_range()

        def compute_range_for_current_video() -> Optional[tuple[str, str]]:
            """
            Normalize start/end input based on video length (or transcript range).

            Rules:
            - Clamp to [0, duration]
            - If both empty -> 0 to duration
            - If only start set -> start to duration
            - If only end set -> 0 to end
            - End must be > start
            - Inputs are updated to normalized values
            - Errors shown next to time inputs (range_error_label)
            """
            duration = get_video_duration()
            if duration is None or duration <= 0:
                if not state.full_segments:
                    range_error_label.text = (
                        "Transcript not loaded; please fetch transcript first."
                    )
                    return None
                duration = get_video_duration()

            raw_start = (start_input.value or "").strip()
            raw_end = (end_input.value or "").strip()

            # Interpret combinations
            if raw_start == "" and raw_end == "":
                start_sec = 0.0
                end_sec = float(duration)
            elif raw_start != "" and raw_end == "":
                start_sec = parse_timecode(raw_start)
                if start_sec is None:
                    range_error_label.text = "Invalid start time format."
                    return None
                end_sec = float(duration)
            elif raw_start == "" and raw_end != "":
                end_sec = parse_timecode(raw_end)
                if end_sec is None:
                    range_error_label.text = "Invalid end time format."
                    return None
                start_sec = 0.0
            else:
                start_sec = parse_timecode(raw_start)
                end_sec = parse_timecode(raw_end)
                if start_sec is None:
                    range_error_label.text = "Invalid start time format."
                    return None
                if end_sec is None:
                    range_error_label.text = "Invalid end time format."
                    return None

            # Clamp to [0, duration]
            start_sec = max(0.0, min(start_sec, duration))
            end_sec = max(0.0, min(end_sec, duration))

            # Enforce end > start
            if end_sec <= start_sec:
                range_error_label.text = "End time must be greater than start time."
                return None

            # Update inputs to normalized values (make defaults explicit)
            norm_start_str = format_timestamp(start_sec)
            norm_end_str = format_timestamp(end_sec)
            start_input.value = norm_start_str
            end_input.value = norm_end_str

            range_error_label.text = ""
            return norm_start_str, norm_end_str

        def update_preview() -> None:
            """Apply current options (time range, display mode, title/description) to the transcript."""
            if not state.full_segments:
                state.current_text = ""
                preview_area.value = ""
                refresh_counts()
                return

            result = compute_range_for_current_video()
            if result is None:
                # invalid range; message already shown via range_error_label
                return
            norm_start_str, norm_end_str = result

            text = build_filtered_text(
                segments=state.full_segments,
                start_str=norm_start_str,
                end_str=norm_end_str,
                display_mode=display_mode.value,
                include_title=include_title_checkbox.value,
                include_description=include_description_checkbox.value,
                video_title=state.video_title,
                video_description=state.video_description,
            )
            state.current_text = text
            preview_area.value = text
            refresh_counts()

        # ---------- button handlers ----------

        async def fetch_transcript() -> None:
            # Progress is ONLY for fetching
            reset_progress()
            action_status_label.text = ""
            range_error_label.text = ""
            fetch_status_label.text = "Parsing URL..."
            set_progress(0.1)

            url = url_input.value or ""
            video_id = extract_video_id(url)
            if not video_id:
                fetch_status_label.text = "Could not extract video ID from URL."
                reset_progress()
                return

            # fetch video metadata (title, description, duration)
            fetch_status_label.text = "Fetching video info..."
            set_progress(0.3)
            try:
                yt = YouTube(url)
                state.video_title = yt.title
                state.video_description = yt.description
                state.video_length = float(getattr(yt, "length", None) or 0.0)
                if state.video_length <= 0:
                    state.video_length = None
            except Exception:
                state.video_title = None
                state.video_description = None
                state.video_length = None
                fetch_status_label.text = "Warning: could not fetch video info."

            # Update hint and default start/end once we know duration
            duration = get_video_duration()
            if duration is not None and duration > 0:
                end_ts = format_timestamp(duration)
                range_hint_label.text = f"Default range is 0 to {end_ts}. "
                # Set explicit defaults in inputs
                start_input.value = "0"
                end_input.value = end_ts
            else:
                range_hint_label.text = (
                    "Clear custom start/end time to use the full video."
                )
                start_input.value = ""
                end_input.value = ""

            # fetch transcript
            fetch_status_label.text = "Fetching transcript..."
            set_progress(0.6)
            try:
                api = YouTubeTranscriptApi()
                fetched = api.fetch(video_id)
                state.full_segments = fetched.to_raw_data()
            except Exception:
                # generic, user-friendly message instead of long library error
                fetch_status_label.text = (
                    "Error fetching transcript: the video URL is invalid, "
                    "unavailable, or has no transcript."
                )
                state.full_segments = []
                reset_progress()
                return

            fetch_status_label.text = "Transcript fetched."
            set_progress(1.0)

            # Initialize preview with default range (0 to full length)
            update_preview()

        def copy_to_clipboard() -> None:
            text = preview_area.value or state.current_text or ""
            if not text:
                action_status_label.text = "Nothing to copy."
            else:
                action_status_label.text = "Copied to clipboard."

        async def run_export(kind: str) -> None:
            """Generic export (no progress bar; progress is only for fetch)."""
            text = preview_area.value or state.current_text or ""
            if not text:
                action_status_label.text = "Nothing to export. Fetch transcript first."
                return

            base_name = file_title_input.value.strip() or "transcript"
            action_status_label.text = f"Exporting as {kind.upper()}..."

            if kind == "txt":
                data = text.encode("utf-8")
                filename = base_name + ".txt"
            elif kind == "csv":
                lines = text.splitlines()
                output = io.StringIO()
                output.write("text\n")
                for line in lines:
                    escaped = line.replace('"', '""')
                    output.write(f'"{escaped}"\n')
                data = output.getvalue().encode("utf-8")
                filename = base_name + ".csv"
            elif kind == "docx":
                doc = Document()
                for paragraph in text.split("\n\n"):
                    doc.add_paragraph(paragraph)
                buf = io.BytesIO()
                doc.save(buf)
                data = buf.getvalue()
                filename = base_name + ".docx"
            elif kind == "pdf":
                pdf = FPDF()
                pdf.set_auto_page_break(auto=True, margin=15)
                pdf.add_page()
                pdf.set_font("Arial", size=11)
                for line in text.split("\n"):
                    pdf.multi_cell(0, 5, line)
                buf = io.BytesIO()
                pdf.output(buf)
                data = buf.getvalue()
                filename = base_name + ".pdf"
            else:
                action_status_label.text = "Unknown export type."
                return

            ui.download(data, filename)
            action_status_label.text = f"Downloaded {filename}."

        def make_export_handler(kind: str):
            async def handler():
                await run_export(kind)

            return handler

        # ---------- wire up events ----------
        fetch_button.on_click(fetch_transcript)
        apply_button.on_click(lambda: update_preview())
        copy_button.on_click(copy_to_clipboard)

        # Restore sensible defaults when time fields are cleared
        start_input.on("blur", on_start_blur)
        end_input.on("blur", on_end_blur)

        export_txt_button.on_click(make_export_handler("txt"))
        export_csv_button.on_click(make_export_handler("csv"))
        export_docx_button.on_click(make_export_handler("docx"))
        export_pdf_button.on_click(make_export_handler("pdf"))


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="YouTube Transcript Exporter", reload=False)
