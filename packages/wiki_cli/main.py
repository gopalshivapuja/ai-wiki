"""`wiki` — bulk ingest and maintenance against a running wiki.

Exists because the last bulk load could not be repeated from what was in the repository. The
capture half has to run on your machine (YouTube refuses cloud addresses); everything else is
a thin wrapper over the API so there is one obvious way to do each job.

    wiki status
    wiki channel https://www.youtube.com/@Someone/videos --moc moc-course --whisper
    wiki crawl https://docs.example.com/guide --collection example-docs --max-pages 200
    wiki embed
    wiki backup ./backups
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from wiki_cli.client import Wiki, WikiError

DEFAULT_WORK_DIR = Path.home() / ".ai-wiki"


def _zip_dir(directory: Path, out: Path) -> Path:
    subprocess.run(["zip", "-qr", str(out), "."], cwd=directory, check=True)
    return out


def cmd_status(wiki: Wiki, args) -> int:
    stats = wiki.get("/stats")
    orphans = wiki.get("/orphans")
    jobs = wiki.get("/jobs", limit=1)
    print(f"notes    {stats['total_notes']}")
    print(f"sources  {stats['total_sources']}")
    print(f"links    {stats['total_wikilinks']} ({stats['avg_links_per_note']} per note)")
    print(f"queue    {jobs.get('active', 0)} active of {jobs.get('total', 0)} jobs")
    dangling = len(orphans["wanted"])
    unlinked = [o["slug"] for o in orphans["unlinked"]]
    print(f"dangling {dangling}" + ("" if dangling == 0 else "  <- links to nothing"))
    print(f"unlinked {len(unlinked)} {unlinked[:5]}")
    return 0 if dangling == 0 else 1


def cmd_embed(wiki: Wiki, args) -> int:
    print(wiki.post("/maintenance/embed", {}))
    if args.duplicates:
        pairs = wiki.get("/maintenance/duplicates")["pairs"]
        print(f"\n{len(pairs)} near-duplicate pair(s) — review before merging any:")
        for p in pairs:
            print(f"  {p['score']:.3f}  {p['a']}  <->  {p['b']}")
        print("\nSimilarity is not sameness: opposites score highly too.")
    return 0


def cmd_crawl(wiki: Wiki, args) -> int:
    job = wiki.post(
        "/jobs/crawl",
        {
            "url": args.url,
            "collection": args.collection,
            "max_pages": args.max_pages,
            "max_depth": args.max_depth,
            "moc": args.moc,
            "moc_title": args.moc_title,
        },
    )
    print(f"queued crawl job {job['id']} for {args.url}")
    if args.wait:
        done = wiki.wait_for_job(job["id"], timeout=args.timeout)
        print(done["status"], done.get("result") or done.get("error"))
    return 0


def cmd_channel(wiki: Wiki, args) -> int:
    """Capture a channel locally, then import it.

    The server cannot do this: YouTube refuses caption requests from cloud IP ranges, so the
    channel ingest job fails there for every video. Capturing here and importing the result is
    the path that works.
    """
    from wiki_cli import capture

    work = Path(args.work_dir).expanduser()
    sources, audio = work / "sources", work / "audio"
    state = capture.CaptureState.load(work / "capture-state.json")

    videos = capture.list_videos(args.url, limit=args.limit)
    print(f"{len(videos)} videos on {args.url}")
    if args.list_only:
        for v in videos:
            print(f"  {v.id}  {v.title}")
        return 0

    result = capture.capture(
        videos,
        out_dir=sources,
        state=state,
        collection=args.collection,
        allow_whisper=args.whisper,
        audio_dir=audio,
        pace=args.pace,
    )
    print(
        f"\ncaptured {result['captured']} ({result['transcribed']} transcribed locally), "
        f"skipped {result['skipped']}"
    )

    pending = sorted(sources.glob("*.md"))
    if not pending:
        print("nothing to import")
        return 1 if result["skipped"] else 0

    # Import only what the wiki does not already hold, so re-running is cheap.
    have = {d["slug"] for d in wiki.get("/documents", doc_class="source", limit=2000)["documents"]}
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "sources"
        staged.mkdir(parents=True)
        new = [p for p in pending if p.stem not in have]
        for p in new:
            shutil.copy(p, staged / p.name)
        if not new:
            print("every captured transcript is already in the wiki")
            return 0
        archive = _zip_dir(Path(tmp), Path(tmp) / "import.zip")
        fields = {"distill": "true"}
        if args.moc:
            fields["moc"] = args.moc
        if args.moc_title:
            fields["moc_title"] = args.moc_title
        job = wiki.upload("/jobs/import", archive, fields)
    print(f"importing {len(new)} transcripts as job {job['id']}")

    finished = wiki.wait_for_job(job["id"], timeout=args.timeout)
    print("import:", finished["status"], finished.get("result") or finished.get("error"))
    if args.wait:
        print("waiting for distillation to drain…")
        wiki.wait_for_queue(on_tick=lambda n: print(f"  {n} jobs active", flush=True))
        cmd_status(wiki, args)
    else:
        print(f"{wiki.queue_depth()} jobs queued; run `wiki status` to follow them")
    return 0


def cmd_backup(wiki: Wiki, args) -> int:
    """Download an export and verify it opens before calling it a backup."""
    import zipfile
    from datetime import datetime

    out_dir = Path(args.directory).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"ai-wiki-{stamp}.zip"

    import urllib.request

    req = urllib.request.Request(
        f"{wiki.url}/api/export", headers={"Authorization": f"Bearer {wiki.token}"}
    )
    with urllib.request.urlopen(req, timeout=900) as response:
        path.write_bytes(response.read())

    # An export that cannot be opened is not a backup. A corrupt archive once passed a check
    # that only listed its contents, so read every member.
    zf = zipfile.ZipFile(path)
    if zf.testzip() is not None:
        path.unlink()
        raise WikiError("The export is corrupt — a member failed its CRC. Backup NOT saved.")
    for name in zf.namelist():
        zf.read(name)
    print(f"{path}  ({path.stat().st_size // 1024}KB, {len(zf.namelist())} files, verified)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wiki", description=__doc__.split("\n")[0])
    p.add_argument("--url", help="wiki base URL (or WIKI_URL)")
    p.add_argument("--token", help="bearer token (or WIKI_TOKEN)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="counts, queue depth and graph health")
    s.set_defaults(func=cmd_status)

    e = sub.add_parser("embed", help="backfill missing embeddings")
    e.add_argument("--duplicates", action="store_true", help="also report near-duplicate notes")
    e.set_defaults(func=cmd_embed)

    c = sub.add_parser("crawl", help="capture a documentation site")
    c.add_argument("url")
    c.add_argument("--collection")
    c.add_argument("--max-pages", type=int, default=100)
    c.add_argument("--max-depth", type=int, default=2)
    c.add_argument("--moc")
    c.add_argument("--moc-title")
    c.add_argument("--wait", action="store_true")
    c.add_argument("--timeout", type=int, default=3600)
    c.set_defaults(func=cmd_crawl)

    y = sub.add_parser("channel", help="capture a YouTube channel locally and import it")
    y.add_argument("url")
    y.add_argument("--limit", type=int, help="only the newest N videos")
    y.add_argument("--collection", default="youtube")
    y.add_argument("--moc")
    y.add_argument("--moc-title")
    y.add_argument(
        "--whisper",
        action="store_true",
        help="transcribe locally when captions are refused (needs the stt extra)",
    )
    y.add_argument("--pace", type=float, default=2.0, help="seconds between videos")
    y.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    y.add_argument("--list-only", action="store_true")
    y.add_argument("--wait", action="store_true", help="wait for distillation to finish")
    y.add_argument("--timeout", type=int, default=3600)
    y.set_defaults(func=cmd_channel)

    b = sub.add_parser("backup", help="download and verify an export")
    b.add_argument("directory")
    b.set_defaults(func=cmd_backup)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(Wiki(url=args.url, token=args.token), args)
    except WikiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted; progress is saved and re-running resumes", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
