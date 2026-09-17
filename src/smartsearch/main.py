"""Orest smart search: build, serve and query the rehearsal search index.

Entry point for the Smart Search affordance of
knowledge/components/02_processing.md.

    orest-search extract                     # embed a folder of rehearsal footage
    orest-search add-extractor --video-id ID # re-embed it with another model
    orest-search index                       # build the nearest-neighbour indices
    orest-search serve                       # run WISE, needed for the queries below
    orest-search info
    orest-search query "zwei Personen streiten"
    orest-search query "..." --send-td       # cut clips and announce them to TouchDesigner
    orest-search body-live --send-td         # search by a movement performed in front of a camera

Equivalently, without the installed entry point:

    python -m smartsearch.main query "..."
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx
from orest_pose import EXTRACTOR_ID as POSE_ID

from . import client, clips, config, td, wise_cli


def _project(parser: argparse.ArgumentParser):
    parser.add_argument("--project", default=config.DEFAULT_PROJECT,
                        help=f"WISE project name (default: {config.DEFAULT_PROJECT})")


def _extractors(parser: argparse.ArgumentParser):
    parser.add_argument("--video-id", action="append", default=[], metavar="ID",
                        help="visual feature extractor; repeatable")
    parser.add_argument("--audio-id", action="append", default=[], metavar="ID",
                        help="audio feature extractor; repeatable")
    parser.add_argument("--image-id", action="append", default=[], metavar="ID",
                        help="still-image feature extractor; repeatable")


def _delivery(parser: argparse.ArgumentParser):
    parser.add_argument("--cut", choices=clips.MODES,
                        help="cut each result into a clip: fast copies the stream, "
                             "precise re-encodes it (default with --send-td: fast)")
    parser.add_argument("--encoder", choices=clips.ENCODERS, default=clips.LIBX264,
                        help=f"H.264 encoder for precise clips (default: {clips.LIBX264})")
    parser.add_argument("--send-td", action="store_true",
                        help=f"announce each clip over OSC to "
                             f"{config.TD_HOST}:{config.TD_PORT}")
    parser.add_argument("--segments", action="store_true",
                        help="return the indexed 4s windows rather than merged spans")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="extract features from a media folder")
    _project(extract)
    _extractors(extract)
    extract.add_argument("--media", default=config.MEDIA_DIR, metavar="DIR",
                         help=f"folder of rehearsal footage (default: {config.MEDIA_DIR})")
    extract.add_argument("--include", action="append", default=[], metavar="GLOB",
                         help="only files matching this glob; repeatable")
    extract.add_argument("--workers", type=int, default=0, help="dataloader workers")
    extract.add_argument("--no-thumbnails", action="store_true",
                         help="skip thumbnail generation")
    extract.add_argument("--autocast", action="store_true",
                         help="mixed precision; not supported by the audio extractor")

    add = commands.add_parser("add-extractor",
                              help="re-embed a project's media with another model")
    _project(add)
    _extractors(add)
    add.add_argument("--autocast", action="store_true")

    index = commands.add_parser("index", help="build search indices over extracted features")
    _project(index)
    index.add_argument("--index-type", default="IndexFlatIP",
                       choices=["IndexFlatIP", "IndexIVFFlat"])
    index.add_argument("--feature-id", help="index only this extractor")
    index.add_argument("--modality", action="append", default=[],
                       choices=["audio", "video", "image"])
    index.add_argument("--overwrite", action="store_true")

    serve = commands.add_parser("serve", help="run the WISE server")
    _project(serve)
    serve.add_argument("--host", default=config.HOST)
    serve.add_argument("--port", type=int, default=config.PORT)
    serve.add_argument("--index-type")

    info = commands.add_parser("info", help="report what a served project contains")
    _project(info)

    body = commands.add_parser("body", help="search by movement, using a clip as the query")
    _project(body)
    body.add_argument("clip", help="video file the query movement is taken from")
    body.add_argument("--at", type=float, default=0.0, metavar="SECONDS",
                      help="where the movement starts in that file (default: 0)")
    body.add_argument("--feature-id", default=POSE_ID,
                      help=f"pose extractor to search (default: {POSE_ID})")
    body.add_argument("-n", "--limit", type=int, default=10)
    _delivery(body)

    live = commands.add_parser("body-live",
                               help="search by a movement performed live: Enter or OSC "
                                    "starts and stops a capture")
    _project(live)
    source = live.add_mutually_exclusive_group()
    source.add_argument("--video", help="camera index or name fragment (default: system default)")
    source.add_argument("--file", help="play a recording in real time in place of a camera")
    live.add_argument("--at", type=float, default=0.0, metavar="SECONDS",
                      help="where playback of --file starts (default: 0)")
    live.add_argument("--feature-id", default=POSE_ID,
                      help=f"pose extractor to search (default: {POSE_ID})")
    live.add_argument("-n", "--limit", type=int, default=10)
    live.add_argument("--per-file", type=int, metavar="N",
                      help="at most N results from any one recording")
    _delivery(live)

    query = commands.add_parser("query", help="search a served project by text")
    _project(query)
    query.add_argument("text", nargs="+", help="query text")
    query.add_argument("--target", default=client.VIDEO,
                       choices=[client.VIDEO, client.AUDIO, client.IMAGE],
                       help="which index to search (default: video)")
    query.add_argument("--feature-id", help="feature extractor; defaults to the first indexed")
    query.add_argument("-n", "--limit", type=int, default=10)
    query.add_argument("--no-prefix", action="store_true",
                       help="send the text as written, without the caption template")
    query.add_argument("--not", dest="negative", action="append", default=[], metavar="TEXT",
                       help="text to search away from; repeatable")
    _delivery(query)

    return parser


def format_info(payload: dict) -> str:
    duration = payload.get("total_duration", 0.0)
    lines = [
        f"project   {payload.get('project_name', '')}",
        f"media     {payload.get('num_media_files', 0)} files, {client.timecode(duration)}",
        f"vectors   {payload.get('num_vectors', 0)}",
        f"thumbs    {payload.get('num_thumbnails', 0)}",
        f"shots     {payload.get('num_shots', 0)}",
        "targets",
    ]
    targets = payload.get("search_targets", {})
    if not targets:
        lines.append("  none — extraction produced nothing, or no index was built")
    for modality, ids in targets.items():
        for extractor_id in ids:
            lines.append(f"  {modality:<8} {extractor_id}")
    return "\n".join(lines)


def format_hits(hits: list[client.Hit]) -> str:
    if not hits:
        return "no results"
    width = max(len(hit.filename) for hit in hits)
    # ASCII only: the Windows console default code page cannot encode the
    # typographic dash, and this table is meant to be redirectable as-is.
    return "\n".join(
        f"{rank:>3}  {hit.score:>7.3f}  {hit.filename:<{width}}  "
        f"{client.timecode(hit.ts)} - {client.timecode(hit.te)}  {hit.media_url}"
        for rank, hit in enumerate(hits, start=1)
    )


def deliver(hits: list[client.Hit], project: str, mode: str, encoder: str,
            send_td: bool):
    """Cut hits into clips in rank order, announcing each one as it is written."""
    sender = td.Sender() if send_td else None
    query_id = td.new_query_id()
    if sender:
        sender.send(td.begin_message(query_id, len(hits)))
    for rank, hit, clip in clips.cut_all(hits, mode, config.clips_dir(project), encoder):
        print(f"{rank:>3}  {clip.path}  preroll {clip.preroll:.3f}s", flush=True)
        if sender:
            sender.send(td.hit_message(query_id, rank, clip, hit))
    if sender:
        sender.send(td.end_message(query_id))


def live_session(wise: client.Wise, args) -> int:
    """Capture movements on demand and search with each, until interrupted."""
    # Imported here so the batch and text commands do not pay for loading the
    # pose model and camera dependencies.
    from . import live

    if args.file:
        source = live.FilePlayback(Path(args.file), args.at)
        where = lambda: f" at {source.position():.1f}s of {Path(args.file).name}"
    else:
        from sitrep import capture, devices

        camera = devices.resolve_video_device(args.video)
        print(f"camera [{camera.index}] {camera.name}")
        source = capture.VideoStream(camera)
        where = lambda: ""

    recorder = live.PoseRecorder(source.latest)
    triggers = live.Triggers()
    began = {}

    def on_start(event):
        began["at"] = time.monotonic()
        print(f"capturing{where()} [start from {live.source(event)}] - Enter or "
              f"{live.STOP_ADDRESS} to stop", flush=True)

    def on_capture(detections, event):
        seconds = time.monotonic() - began["at"]
        windows = live.query_windows(detections)
        print(f"captured {seconds:.1f}s{where()} [stop from {live.source(event)}]: "
              f"{len(detections)} poses, "
              f"{len(windows)} query window{'s' if len(windows) != 1 else ''}", flush=True)
        hits = live.search(wise, detections, feature_id=args.feature_id,
                           limit=args.limit, per_file=args.per_file,
                           merged=not args.segments)
        if not hits:
            print("No body found in the capture.", flush=True)
            return
        print(format_hits(hits), flush=True)
        if args.cut or args.send_td:
            deliver(hits, args.project, args.cut or clips.FAST, args.encoder, args.send_td)

    try:
        while not recorder.ready:
            time.sleep(0.1)
        print(f"ready - Enter or {live.START_ADDRESS} on "
              f"{config.CONTROL_HOST}:{config.CONTROL_PORT} starts a capture", flush=True)
        live.run(recorder, triggers, on_start, on_capture)
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        triggers.close()
        recorder.close()
        source.close()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    project = config.project_dir(args.project)

    if args.command == "extract":
        return wise_cli.extract(
            project, [args.media],
            video_ids=args.video_id, audio_ids=args.audio_id, image_ids=args.image_id,
            include=args.include, num_workers=args.workers,
            thumbnails=not args.no_thumbnails, autocast=args.autocast,
        )

    if args.command == "add-extractor":
        if not (args.video_id or args.audio_id or args.image_id):
            print("Name at least one feature extractor to add.", file=sys.stderr)
            return 1
        # No media directories: WISE re-embeds the media already registered in
        # the project rather than scanning the source folder again.
        #
        # Thumbnails are off. They were generated when the media was first
        # added and are keyed by media and timestamp, not by extractor, so a
        # second pass decodes them again and appends a duplicate set.
        return wise_cli.extract(
            project,
            video_ids=args.video_id, audio_ids=args.audio_id, image_ids=args.image_id,
            autocast=args.autocast, thumbnails=False,
        )

    if args.command == "index":
        return wise_cli.create_index(
            project, index_type=args.index_type, modalities=args.modality,
            feature_id=args.feature_id, overwrite=args.overwrite,
        )

    if args.command == "serve":
        print(f"serving {project} at {config.base_url()}/{args.project}/")
        return wise_cli.serve(project, host=args.host, port=args.port,
                              index_type=args.index_type)

    with client.Wise(args.project) as wise:
        try:
            if args.command == "info":
                print(format_info(wise.info()))
                return 0

            if args.command == "body-live":
                return live_session(wise, args)

            if args.command == "body":
                # Imported here so the batch and text commands do not pay for
                # loading the pose model's dependencies.
                from . import pose

                vector = pose.encode_clip(args.clip, args.at)
                if not vector.any():
                    print(f"No body found in {args.clip} at {args.at:g}s.", file=sys.stderr)
                    return 1
                hits = wise.search_vector(
                    vector,
                    feature_extractor_id=args.feature_id,
                    limit=args.limit,
                    merged=not args.segments,
                )
                print(format_hits(hits))
                if args.cut or args.send_td:
                    deliver(hits, args.project, args.cut or clips.FAST,
                            args.encoder, args.send_td)
                return 0

            hits = wise.search(
                " ".join(args.text),
                negative_text=args.negative,
                target=args.target,
                feature_extractor_id=args.feature_id,
                limit=args.limit,
                add_prefix=not args.no_prefix,
                merged=not args.segments,
            )
            print(format_hits(hits))
            if args.cut or args.send_td:
                deliver(hits, args.project, args.cut or clips.FAST,
                        args.encoder, args.send_td)
            return 0
        except httpx.HTTPStatusError as error:
            print(f"{error.response.status_code}: {error.response.text}", file=sys.stderr)
            return 1
        except httpx.RequestError:
            print(f"No WISE server at {wise.base_url}. Start one with "
                  f"'orest-search serve'.", file=sys.stderr)
            return 1
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 1
        except subprocess.CalledProcessError as error:
            # ffmpeg has already printed its own error above.
            print(f"ffmpeg exited with {error.returncode} while cutting a clip.",
                  file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
