"""Audio transcription for video/podcast URLs that have no captions.

Uses yt-dlp to pull a low-bitrate audio track, then a hosted speech-to-text API. Whisper is
about $0.006/min and Deepgram about $0.004/min, so an hour of audio costs well under a
dollar — and neither adds resident memory to the container, unlike self-hosting Whisper.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import tempfile
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session
from wiki_core.utils import slugify

from wiki_api.services.content import log_action, upsert_source
from wiki_api.services.fetch import MAX_AUDIO_BYTES, clamp

logger = logging.getLogger(__name__)

# Whisper's API rejects uploads above 25MB.
MAX_UPLOAD_BYTES = 25_000_000

ProgressFn = Callable[[int, int, str], None]


class TranscriptionError(ValueError):
    """Transcription could not be completed. Safe to show to the user."""


def stt_provider() -> str:
    return os.environ.get("STT_PROVIDER", "openai").strip().lower()


def is_configured() -> bool:
    provider = stt_provider()
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if provider == "deepgram":
        return bool(os.environ.get("DEEPGRAM_API_KEY", "").strip())
    return False


def download_audio(
    url: str, dest_dir: Path, on_progress: ProgressFn | None = None
) -> tuple[Path, dict]:
    """Download the audio track of a video URL. Returns (path, metadata)."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise TranscriptionError("yt-dlp is not installed") from exc

    outtmpl = str(dest_dir / "audio.%(ext)s")
    opts = {
        # Smallest usable audio: speech-to-text gains nothing from a 320kbps stereo track.
        "format": "worstaudio/bestaudio",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_AUDIO_BYTES,
        "socket_timeout": 30,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "32"}
        ],
        # Mono 16kHz — speech-to-text gains nothing from stereo or a high sample rate.
        "postprocessor_args": {"extractaudio": ["-ac", "1", "-ar", "16000"]},
    }

    if on_progress:
        on_progress(1, 3, "Downloading audio")

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except Exception as exc:
            raise TranscriptionError(f"Could not download audio: {exc}") from exc

    files = sorted(dest_dir.glob("audio.*"))
    if not files:
        raise TranscriptionError("yt-dlp produced no audio file")
    path = files[0]

    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise TranscriptionError(
            f"Audio is {size // 1_000_000}MB, above the {MAX_UPLOAD_BYTES // 1_000_000}MB "
            "limit of the transcription API. Long recordings are not supported yet."
        )

    meta = {
        "title": info.get("title") or url,
        "channel": info.get("uploader") or info.get("channel") or "Unknown",
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
    }
    return path, meta


def _multipart(
    fields: dict[str, str], file_path: Path, file_field: str = "file"
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        disposition = f'Content-Disposition: form-data; name="{key}"'
        parts.append(f"--{boundary}\r\n{disposition}\r\n\r\n{value}\r\n".encode())
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_path.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _stt_openai(path: Path) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise TranscriptionError("OPENAI_API_KEY is not set")
    model = os.environ.get("STT_MODEL", "whisper-1")
    body, content_type = _multipart({"model": model, "response_format": "text"}, path)
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.read().decode("utf-8", errors="ignore").strip()
    except Exception as exc:
        raise TranscriptionError(f"OpenAI transcription failed: {exc}") from exc


def _stt_deepgram(path: Path) -> str:
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not key:
        raise TranscriptionError("DEEPGRAM_API_KEY is not set")
    model = os.environ.get("STT_MODEL", "nova-2")
    ctype = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?model={model}&smart_format=true&punctuate=true",
        data=path.read_bytes(),
        headers={"Authorization": f"Token {key}", "Content-Type": ctype},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode())
        return data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
    except Exception as exc:
        raise TranscriptionError(f"Deepgram transcription failed: {exc}") from exc


def transcribe_file(path: Path) -> str:
    provider = stt_provider()
    if provider == "openai":
        return _stt_openai(path)
    if provider == "deepgram":
        return _stt_deepgram(path)
    raise TranscriptionError(
        f"Unknown STT_PROVIDER '{provider}' — set it to 'openai' or 'deepgram'"
    )


def ingest_audio(db: Session, url: str, on_progress: ProgressFn | None = None) -> dict:
    if not is_configured():
        raise TranscriptionError(
            f"Transcription is not configured. Set STT_PROVIDER and the matching API key "
            f"(currently STT_PROVIDER={stt_provider()})."
        )

    # TemporaryDirectory cleans up on every exit path, including cancellation.
    with tempfile.TemporaryDirectory(prefix="wiki-audio-") as tmp:
        path, meta = download_audio(url, Path(tmp), on_progress)
        if on_progress:
            on_progress(2, 3, f"Transcribing {path.stat().st_size // 1_000_000}MB of audio")
        transcript = transcribe_file(path)

    if not transcript.strip():
        raise TranscriptionError("The transcription came back empty")

    title = meta["title"]
    slug = slugify(title) or f"audio-{uuid.uuid4().hex[:8]}"
    duration = meta.get("duration")
    header = f"# {title}\n\n**Channel:** {meta['channel']}\n"
    if duration:
        header += f"**Duration:** {int(duration) // 60}m {int(duration) % 60}s\n"
    header += f"**Source:** [{meta['webpage_url']}]({meta['webpage_url']})\n\n"

    content = clamp(f"{header}## Transcript\n\n{transcript}")
    source, created = upsert_source(
        db,
        slug,
        title,
        content,
        "audio",
        url=meta["webpage_url"],
        extra={
            "channel": meta["channel"],
            "duration": duration,
            "transcript_source": stt_provider(),
        },
    )
    if on_progress:
        on_progress(3, 3, "Stored transcript")
    if created:
        log_action(db, "ingest", f"Transcribed: {title}")
    return {"slug": source.slug, "title": title, "type": "audio", "created": created}
