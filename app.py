from __future__ import annotations

from typing import Optional

from docx import Document
from fpdf import FPDF
from nicegui import ui
from pathlib import Path
from pytubefix import YouTube
from youtube_transcript_api import YouTubeTranscriptApi


import io

from transcript_utils import (
    AppState,
    build_filtered_text,
    estimate_file_size_bytes,
    extract_video_id,
    format_size,
    format_timestamp,
    get_video_duration,
    parse_timecode,
    sanitize_filename,
)

YOUTUBE_RED = "red-5"
GLOBAL_CSS = Path("styles/global.css").read_text(encoding="utf-8")


@ui.page("/")
def main_page() -> None:
    """Main NiceGUI page for the YouTube Transcript Downloader."""
    # page-scoped CSS (allowed with ui.page)
    ui.add_css(GLOBAL_CSS)

    # Central state container
    state = AppState()

    # OUTER SHELL: centers everything
    with ui.column().classes(
        "items-center justify-start w-full"
    ).style("min-height: 100vh; padding: 32px 16px;"):

        # INNER WRAPPER: same width for header + card
        with ui.column().classes("app-inner items-center w-full"):

            # Header with icon + centered title
            with ui.row().classes("items-center justify-center gap-3").style(
                "margin-bottom: 16px;"
            ):
                ui.image("images/icon.png").style(
                    "width: 40px; height: 40px; border-radius: 12px; "
                    "box-shadow: 0 4px 10px rgba(0,0,0,0.15);"
                )
                with ui.column().classes("gap-0 items-center"):
                    ui.label("YouTube Transcript Downloader").classes(
                        "text-2xl font-semibold text-gray-900"
                    )
                    ui.label(
                        "Extract, trim, and export YouTube transcripts with ease."
                    ).classes("text-sm text-gray-600")

            # Main card: full width of app-inner
            with ui.card().classes("w-full").style(
                "max-width: 960px; "
                "border-radius: 18px; "
                "background: white; "
                "box-shadow: 0 18px 40px rgba(15,23,42,0.18); "
                "padding: 20px 24px 24px 24px;"
            ):
                # URL + fetch row
                ui.label("1. Paste a YouTube URL").classes(
                    "text-sm font-medium text-gray-800"
                )

                url_input = (
                    ui.input(
                        "",
                        placeholder="https://www.youtube.com/watch?v=...",
                    )
                    .props("clearable outlined")
                    .style("width: 100%; margin-top: 4px;")
                )

                with ui.column().classes("w-full").style(
                    "margin-top: 10px; margin-bottom: 8px;"
                ):
                    # First row: fetch button + progress bar
                    with ui.row().classes("items-center gap-3 justify-between fetch-row"):
                        fetch_button = ui.button(
                            "Fetch transcript",
                            icon="download",
                            color=YOUTUBE_RED,
                        ).props("unelevated rounded")

                        # PROGRESS BAR for fetch (now red)
                        with ui.row().classes("items-center gap-2"):
                            progress = (
                                ui.linear_progress(
                                    value=0,
                                    show_value=False,
                                    size="30px",
                                    color=YOUTUBE_RED,
                                )
                                .props("striped instant-feedback")
                                .style(
                                    "width: 260px; border-radius: 999px; overflow: hidden;"
                                )
                            )
                            # overlayed percentage label bound to progress.value
                            with progress:
                                progress_label = (
                                    ui.label("0%")
                                    .classes(
                                        "text-xs text-white absolute-center font-medium"
                                    )
                                    .bind_text_from(
                                        progress,
                                        "value",
                                        backward=lambda v: f"{int(v * 100)}%",
                                    )
                                )

                    # Second row: status text under button + progress
                    fetch_status_label = ui.label("").classes("text-xs text-gray-600")

                ui.separator().props("inset").style("margin: 12px 0 16px 0;")

                # ---------- OPTIONS UI ----------
                ui.label("2. Configure transcript options").classes(
                    "text-sm font-medium text-gray-800"
                )

                with ui.expansion(
                    "Time range, formatting, and metadata",
                    icon="settings",
                    value=True,
                ).props("dense expand-icon=keyboard_arrow_down"):
                    # Start/End time row with arrow buttons
                    with ui.row().classes("items-center time-row").style(
                        "gap: 12px; margin-top: 4px;"
                    ):
                        # START
                        with ui.column().classes("gap-1"):
                            ui.label("Start time").classes("text-xs text-gray-700")
                            with ui.row().classes("items-center").style("gap: 4px;"):
                                start_input = (
                                    ui.input("", placeholder="e.g. 0:30")
                                    .props("outlined dense")
                                    .classes("time-input")
                                    .style("width: 140px;")
                                )

                                # Triangle buttons
                                with ui.column().classes("items-center").style(
                                    "margin-left: -10px; gap: 3px;"
                                ):
                                    ui.button(
                                        icon="arrow_drop_up",
                                        on_click=lambda: adjust_start(+5),
                                    ).props("dense flat round").style(
                                        "padding: 0; width: 16px; height: 14px; "
                                        "min-height: 14px; font-size: 16px;"
                                    )

                                    ui.button(
                                        icon="arrow_drop_down",
                                        on_click=lambda: adjust_start(-5),
                                    ).props("dense flat round").style(
                                        "padding: 0; width: 16px; height: 14px; "
                                        "min-height: 14px; font-size: 16px;"
                                    )

                        # END
                        with ui.column().classes("gap-1"):
                            ui.label("End time").classes("text-xs text-gray-700")
                            with ui.row().classes("items-center").style("gap: 4px;"):
                                end_input = (
                                    ui.input("", placeholder="e.g. 12:57")
                                    .props("outlined dense")
                                    .classes("time-input")
                                    .style("width: 140px;")
                                )

                                # Triangle buttons
                                with ui.column().classes("items-center").style(
                                    "margin-left: -10px; gap: 3px;"
                                ):
                                    ui.button(
                                        icon="arrow_drop_up",
                                        on_click=lambda: adjust_end(+5),
                                    ).props("dense flat round").style(
                                        "padding: 0; width: 16px; height: 14px; "
                                        "min-height: 14px; font-size: 16px;"
                                    )

                                    ui.button(
                                        icon="arrow_drop_down",
                                        on_click=lambda: adjust_end(-5),
                                    ).props("dense flat round").style(
                                        "padding: 0; width: 16px; height: 14px; "
                                        "min-height: 14px; font-size: 16px;"
                                    )

                    # Error + hint
                    range_error_label = ui.label("").style(
                        "font-size: 0.8rem; color: #d32f2f; margin-top: 4px;"
                    )
                    range_hint_label = ui.label(
                        "After fetching a video, defaults are 0 to full length."
                    ).style("font-size: 0.8rem; color: gray; margin-top: 2px;")

                    # Display mode + include options
                    with ui.row().classes("items-start").style("margin-top: 10px;"):
                        display_mode = (
                            ui.select(
                                label="Transcript display style",
                                options={
                                    "ts_newline": "Timestamp on its own line",
                                    "ts_before": "Timestamp before text (same line)",
                                    "ts_after": "Timestamp after text (same line)",
                                    "no_ts_lines": "No timestamp, keep line breaks",
                                    "no_ts_block": "No timestamp, single block of text",
                                },
                                value="ts_before",
                            )
                            .props("outlined dense")
                            .classes("full-width-mobile")
                            .style("width: 360px;")
                        )

                        with ui.column().classes("gap-1").style("margin-left: 12px;"):
                            include_title_checkbox = ui.checkbox(
                                "Include YouTube title in output", value=True
                            )
                            include_description_checkbox = ui.checkbox(
                                "Include YouTube description in output", value=False
                            )

                    file_title_input = (
                        ui.input(
                            "Output file base name",
                            value="transcript",
                        )
                        .props("outlined dense")
                        .classes("full-width-mobile")
                        .style("width: 260px; margin-top: 10px;")
                    )

                # "Apply options" right after Options, before preview
                with ui.row().classes("items-center justify-end").style(
                    "margin-top: 10px;"
                ):
                    apply_button = ui.button(
                        "Apply options",
                        icon="tune",
                        color=YOUTUBE_RED,
                    ).props("unelevated rounded")

                ui.separator().props("inset").style("margin: 16px 0 16px 0;")

                # COUNTS (progress is above, near fetch)
                with ui.row().classes("items-center justify-between"):
                    ui.label("3. Review and edit transcript").classes(
                        "text-sm font-medium text-gray-800"
                    )
                    counts_label = ui.label(
                        "Words: 0 | Characters: 0 | Est. size: 0 B"
                    ).classes("text-xs text-gray-600")

                ui.label("Transcript preview (editable)").classes(
                    "text-xs text-gray-600"
                ).style("margin-top: 6px;")

                preview_area = (
                    ui.textarea()
                    .props("rows=10 outlined")
                    .classes("text-sm")
                    .style(
                        "width: 100%; height: 260px; overflow-y: auto; "
                        "border-radius: 10px;"
                    )
                )

                ui.separator().props("inset").style("margin: 16px 0 12px 0;")

                ui.label("4. Copy or export").classes("text-sm font-medium text-gray-800")

                with ui.row().classes("items-center gap-2 export-row").style("margin-top: 6px;"):
                    copy_button = ui.button(
                        "Copy to clipboard",
                        icon="content_copy",
                        color=YOUTUBE_RED,
                    ).props("outline rounded")

                    export_txt_button = ui.button(
                        "Download TXT", color=YOUTUBE_RED, icon="description"
                    ).props("unelevated rounded")
                    export_csv_button = ui.button(
                        "Download CSV", color=YOUTUBE_RED, icon="table_chart"
                    ).props("unelevated rounded")
                    export_docx_button = ui.button(
                        "Download DOCX", color=YOUTUBE_RED, icon="article"
                    ).props("unelevated rounded")
                    export_pdf_button = ui.button(
                        "Download PDF", color=YOUTUBE_RED, icon="picture_as_pdf"
                    ).props("unelevated rounded")

                action_status_label = (
                    ui.label("").classes("text-xs text-gray-600").style("margin-top: 4px;")
                )

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

                # ---------- helpers (UI-related) ----------

                def set_progress(value: float) -> None:
                    """Update progress bar (0–1 -> 0–100%)."""
                    value_clamped = max(0.0, min(1.0, float(value)))
                    progress.value = value_clamped
                    # progress_label is already bound to progress.value; this is kept
                    # to preserve previous behavior exactly.
                    progress_label.text = f"{int(value_clamped * 100)}%"

                def reset_progress() -> None:
                    set_progress(0.0)

                def refresh_counts() -> None:
                    text = state.current_text or ""
                    words = len(text.split())
                    chars = len(text)
                    size_bytes = estimate_file_size_bytes(text)
                    counts_label.text = f"Words: {words} | Characters: {chars} | Est. size: {format_size(size_bytes)}"

                def reset_to_full_range() -> None:
                    """Set start/end inputs to the full video range 0 → duration."""
                    duration = get_video_duration(state)
                    if not duration or duration <= 0:
                        return
                    start_input.value = "0"
                    end_input.value = format_timestamp(duration)
                    range_error_label.text = ""

                def adjust_time_input(input_component, delta_seconds: float) -> None:
                    """
                    Nudge a time input up or down by delta_seconds, clamped to [0, video_duration].

                    - Uses existing parse_timecode / format_timestamp behavior
                    - Clears any range error when setting a valid time
                    """
                    duration = get_video_duration(state)
                    if not duration or duration <= 0:
                        # no video loaded yet -> nothing to adjust
                        return

                    raw = (input_component.value or "").strip()
                    current_sec = parse_timecode(raw)
                    if current_sec is None:
                        # if the field is empty or invalid, treat as 0 before adjusting
                        current_sec = 0.0

                    new_sec = max(0.0, min(current_sec + delta_seconds, duration))
                    input_component.value = format_timestamp(new_sec)
                    range_error_label.text = ""

                def adjust_start(delta_seconds: float) -> None:
                    adjust_time_input(start_input, delta_seconds)

                def adjust_end(delta_seconds: float) -> None:
                    adjust_time_input(end_input, delta_seconds)

                def on_start_blur(_event) -> None:
                    """
                    When the start field loses focus:
                    - If both start and end are empty -> reset to full range (0 → duration)
                    - If only start is empty        -> set start = 0
                    """
                    duration = get_video_duration(state)
                    if not duration or duration <= 0:
                        return

                    s_val = (start_input.value or "").strip()
                    e_val = (end_input.value or "").strip()

                    if s_val == "" and e_val == "":
                        # both cleared: full range
                        reset_to_full_range()
                    elif s_val == "":
                        # only start cleared: default to 0
                        start_input.value = "0"
                        range_error_label.text = ""

                def on_end_blur(_event) -> None:
                    """
                    When the end field loses focus:
                    - If end is empty (regardless of start) -> reset BOTH to full range 0 → duration
                    """
                    duration = get_video_duration(state)
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
                    duration = get_video_duration(state)
                    if duration is None or duration <= 0:
                        if not state.full_segments:
                            range_error_label.text = (
                                "Transcript not loaded; please fetch transcript first."
                            )
                            return None
                        duration = get_video_duration(state)

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
                    """Fetch video metadata, transcript, and initialize the preview."""
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
                            # NEW: set default output name to the video title
                        if state.video_title:
                            file_title_input.value = sanitize_filename(state.video_title)
                        else:
                            file_title_input.value = "transcript"
                    except Exception:
                        state.video_title = None
                        state.video_description = None
                        state.video_length = None
                        fetch_status_label.text = "Warning: could not fetch video info."

                    # Update hint and default start/end once we know duration
                    duration = get_video_duration(state)
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
                        action_status_label.text = (
                            "Nothing to export. Fetch transcript first."
                        )
                        return

                    raw_name = (file_title_input.value or "").strip()

                    if raw_name:
                        base_name = sanitize_filename(raw_name)
                    elif state.video_title and state.video_title.strip():
                        base_name = sanitize_filename(state.video_title.strip())
                    else:
                        base_name = "transcript"

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
                    async def handler() -> None:
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
    ui.run(
        title="YouTube Transcript Downloader",
        favicon="images/icon.png",
        reload=False,
    )
