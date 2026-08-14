"""Capture YouTube transcripts locally, because the server cannot.

YouTube refuses caption requests from cloud IP ranges, and from a home address that has asked
too often. Both of the app's routes — the timedtext endpoint and yt-dlp's player negotiation —
were refused from Railway, so the channel ingest job cannot work there. This is not a
workaround for a bug; it is where the work has to happen.

Audio is served freely from the media CDN even while captions are refused, so when captions
fail the fallback is to download the audio and transcribe it locally with Whisper. That is how
28 of 62 lectures were recovered, and the transcripts came out better than the auto-captions.

State is written after every video, so an interrupted run resumes instead of restarting.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

CAPTION_LANGS = ("en", "en-US", "en-GB", "en-orig")
# Audio formats to try in order. The default choice sometimes 403s on a signed URL while a
# specific itag succeeds — the last video of the channel needed exactly this.
AUDIO_FORMATS = ("bestaudio[ext=m4a]/bestaudio", "139", "140", "251", "18")


@dataclass
class Video:
    id: str
    title: str
    duration: int | None = None


@dataclass
class CaptureState:
    """Resumable progress, shared across runs."""

    path: Path
    done: dict = field(default_factory=dict)
    failed: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> CaptureState:
        if path.exists():
            raw = json.loads(path.read_text())
            return cls(path=path, done=raw.get("done", {}), failed=raw.get("failed", {}))
        return cls(path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"done": self.done, "failed": self.failed}, indent=1))

    def outstanding(self, videos: list[Video]) -> list[Video]:
        return [v for v in videos if v.id not in self.done]


def list_videos(url: str, limit: int | None = None) -> list[Video]:
    """List a channel or playlist without downloading anything."""
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "socket_timeout": 30,
    }
    if limit:
        opts["playlistend"] = limit
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return [
        Video(id=e["id"], title=e.get("title") or e["id"], duration=e.get("duration"))
        for e in (info.get("entries") or [])
        if e.get("id") and len(e["id"]) == 11
    ]


def _caption_text(info: dict) -> str | None:
    tracks = {**(info.get("subtitles") or {}), **(info.get("automatic_captions") or {})}
    lang = next((k for k in CAPTION_LANGS if k in tracks), None)
    if not lang:
        return None
    fmt = next((f for f in tracks[lang] if f.get("ext") == "json3"), None)
    if not fmt:
        return None

    for attempt in range(3):
        try:
            with urllib.request.urlopen(fmt["url"], timeout=90) as response:
                data = json.loads(response.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 2:
                return None
            time.sleep(30 * (attempt + 1))
    else:
        return None

    lines: list[str] = []
    for event in data.get("events") or []:
        text = "".join(seg.get("utf8", "") for seg in (event.get("segs") or [])).strip()
        # Auto-captions scroll, repeating the previous line; keep one copy of each.
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    return "\n".join(lines).strip() or None


def fetch_captions(video_id: str) -> str | None:
    """Published captions, or None when YouTube will not serve them."""
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "socket_timeout": 45,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception:
        return None
    return _caption_text(info)


def transcribe_locally(video_id: str, audio_dir: Path, model: str | None = None) -> str | None:
    """Download the audio and transcribe it. Requires the `stt` extra."""
    try:
        import mlx_whisper
    except ImportError:
        raise RuntimeError(
            "Local transcription needs the stt extra: pip install -e '.[stt]'"
        ) from None
    import yt_dlp

    audio_dir.mkdir(parents=True, exist_ok=True)
    downloaded = None
    for fmt in AUDIO_FORMATS:
        try:
            with yt_dlp.YoutubeDL(
                {
                    "quiet": True,
                    "no_warnings": True,
                    "format": fmt,
                    "outtmpl": str(audio_dir / "%(id)s.%(ext)s"),
                    "socket_timeout": 60,
                }
            ) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            downloaded = next(audio_dir.glob(f"{video_id}.*"), None)
            if downloaded:
                break
        except Exception:
            continue
    if not downloaded:
        return None

    try:
        result = mlx_whisper.transcribe(
            str(downloaded),
            path_or_hf_repo=model or "mlx-community/whisper-large-v3-turbo",
            language="en",
            verbose=False,
        )
        return _paragraphs(result.get("segments") or [])
    finally:
        downloaded.unlink(missing_ok=True)


def _paragraphs(segments: list[dict]) -> str:
    """Group segments on pauses, so a transcript reads as prose rather than caption lines."""
    out: list[str] = []
    buf: list[str] = []
    last_end = 0.0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if buf and (seg.get("start", 0) - last_end > 1.6 or len(" ".join(buf)) > 700):
            out.append(" ".join(buf))
            buf = []
        buf.append(text)
        last_end = seg.get("end", last_end)
    if buf:
        out.append(" ".join(buf))
    return "\n\n".join(out)


# University courses repeat their own name in every video title. Stanford CS336 spends
# "Stanford CS336 Language Modeling from Scratch | Spring 2026 | " — 62 characters — before
# saying anything, and a slug has 80 to work with, so eighteen lectures would produce eighteen
# slugs distinguished only by their final few characters.
#
# The pattern is anchored on "Stanford CS<digits>" followed by two pipe-separated segments,
# which matches none of the 196 sources already captured. That is checked by a test rather
# than asserted here, because the slug is derived from the title: a normaliser that caught an
# existing title would re-slug a source already in the database and import it a second time.
_COURSE_BOILERPLATE = re.compile(r"^Stanford\s+(CS\d+)\b[^|]*\|\s*[^|]*\|\s*", re.I)


def normalise_title(title: str) -> str:
    """Cut a course's repeated boilerplate, keeping the part that identifies the lecture."""
    short = _COURSE_BOILERPLATE.sub(r"\1 ", title)
    # Escapes rather than literals: these are en and em dashes, which lecture titles use as
    # separators and which are indistinguishable from a hyphen on sight.
    short = re.sub(r"\s+", " ", short).strip(" -\u2013\u2014:|")
    return short or title


def module_of(title: str) -> str:
    m = re.search(r"Module\s+(\d+)\.", title)
    if m:
        return f"module-{m.group(1)}"
    # Graduate courses number lectures, not modules. Zero-padded so lecture-02 sorts before
    # lecture-10 rather than after it.
    m = re.search(r"\bLecture\s+(\d+)\b", title, re.I)
    if m:
        return f"lecture-{int(m.group(1)):02d}"
    return "live-sessions" if ("Live Session" in title or "Week" in title) else "other"


def write_source(out_dir: Path, video: Video, text: str, collection: str, via: str) -> Path:
    """Write one transcript in the archive format import understands."""
    import yaml
    from wiki_core.utils import slugify

    url = f"https://www.youtube.com/watch?v={video.id}"
    # The importer derives the slug from the title, not from this filename, so shortening the
    # title is what shortens the slug.
    short = normalise_title(video.title)
    front = {
        "title": short,
        "class": "source",
        "type": "youtube",
        "url": url,
        "collection": collection,
        "module": module_of(video.title),  # matched against the full title
    }
    if short != video.title:
        # The title as YouTube published it is still how you would search for the lecture,
        # and an alias is a wikilink target too.
        front["aliases"] = [video.title]
    # yaml.safe_dump rather than f-string quoting: one lecture title contained its own double
    # quotes and produced frontmatter that silently failed to parse.
    meta = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    note = (
        "\n*Transcribed locally with Whisper; YouTube would not serve captions for this video.*\n"
        if via == "whisper"
        else ""
    )
    minutes = f" · {video.duration // 60}m" if video.duration else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Must slugify the same string the importer will, or cmd_channel's "we already have this
    # slug" check stops matching and every transcript is imported a second time.
    path = out_dir / f"src-{slugify(short)}"[:80]
    path = path.with_suffix(".md")
    path.write_text(
        f"---\n{meta}\n---\n\n# {short}\n\n"
        f"**Video:** [{url}]({url}){minutes}\n{note}\n## Transcript\n\n{text}\n"
    )
    return path


def capture(
    videos: list[Video],
    out_dir: Path,
    state: CaptureState,
    collection: str,
    allow_whisper: bool,
    audio_dir: Path,
    pace: float = 2.0,
    log=print,
) -> dict:
    """Capture each video, skipping and logging failures rather than aborting the batch."""
    captured, transcribed, skipped = 0, 0, 0
    todo = state.outstanding(videos)
    log(f"{len(todo)} of {len(videos)} still to capture")

    for i, video in enumerate(todo, start=1):
        text, via = fetch_captions(video.id), "captions"
        if not text and allow_whisper:
            log(f"[{i}/{len(todo)}] no captions, transcribing: {video.title[:56]}")
            try:
                text, via = transcribe_locally(video.id, audio_dir), "whisper"
            except RuntimeError as exc:
                log(f"  {exc}")
                text = None
        if not text:
            state.failed[video.id] = "no captions, and local transcription unavailable or failed"
            state.save()
            skipped += 1
            log(f"[{i}/{len(todo)}] SKIP {video.title[:56]}")
            continue

        path = write_source(out_dir, video, text, collection, via)
        state.done[video.id] = {
            "slug": path.stem,
            "title": video.title,
            "chars": len(text),
            "via": via,
        }
        state.failed.pop(video.id, None)
        state.save()
        captured += 1
        transcribed += via == "whisper"
        log(f"[{i}/{len(todo)}] {video.title[:56]:56} {len(text):>7,} chars ({via})")
        time.sleep(pace)

    return {"captured": captured, "transcribed": transcribed, "skipped": skipped}
