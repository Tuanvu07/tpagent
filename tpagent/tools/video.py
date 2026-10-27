"""Video tools for short talking-head ads (TikTok/Reels) built on ffmpeg/ffprobe.

Every tool validates inputs, never overwrites its input, writes the result next
to the source file with a suffix, and returns the output path + new duration.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import Tool

FFMPEG = os.environ.get("TPAGENT_FFMPEG") or shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
FFPROBE = os.environ.get("TPAGENT_FFPROBE") or shutil.which("ffprobe") or "/usr/local/bin/ffprobe"
PRESETS: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


# --- helpers ----------------------------------------------------------------
def _run_ffmpeg(args: list[str], timeout: int = 600) -> str:
    """Run ffmpeg quietly; raise RuntimeError with stderr on failure."""
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr.strip()[-2000:]}")
    return proc.stderr


def _probe(path: str) -> dict[str, Any]:
    cmd = [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def _streams(info: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [s for s in info.get("streams", []) if s.get("codec_type") == kind]


def _duration(path: str) -> float:
    info = _probe(path)
    dur = info.get("format", {}).get("duration")
    if dur is None:
        return 0.0
    return float(dur)


def _fps(stream: dict[str, Any]) -> float:
    num, _, den = (stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1").partition("/")
    try:
        return round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        return 30.0


def _check(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"input not found: {path}")
    return p


def _out_path(src: Path, suffix: str, out: str | None, ext: str | None = None) -> Path:
    if out:
        o = Path(out).expanduser()
    else:
        o = src.with_name(f"{src.stem}_{suffix}{ext or src.suffix or '.mp4'}")
    if o.resolve() == src.resolve():
        raise ValueError("output path must differ from input (never overwrite input)")
    o.parent.mkdir(parents=True, exist_ok=True)
    return o


def _done(out: Path, extra: str = "") -> str:
    msg = f"OK -> {out} (duration {_duration(str(out)):.2f}s)"
    return f"{msg}\n{extra}" if extra else msg


def _find_font() -> str | None:
    return next((f for f in _FONT_CANDIDATES if Path(f).is_file()), None)


def _fesc(s: str) -> str:
    """Escape a string for use inside an ffmpeg filter option value."""
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _has_audio(path: str) -> bool:
    return bool(_streams(_probe(path), "audio"))


def _vencode_args() -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def _encode_args() -> list[str]:
    return [*_vencode_args(), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]


def _fit_filter(w: int, h: int, mode: str) -> str:
    if mode == "pad":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def write_srt(segments: list[tuple[float, float, str]], path: str) -> str:
    """Write (start, end, text) segments as an SRT file; returns the path."""
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    lines = [f"{i}\n{ts(s)} --> {ts(e)}\n{text.strip()}\n" for i, (s, e, text) in enumerate(segments, 1)]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return path


# --- tools ------------------------------------------------------------------
def video_info(path: str) -> str:
    _check(path)
    info = _probe(path)
    fmt = info.get("format", {})
    out: dict[str, Any] = {"path": path, "duration": round(float(fmt.get("duration", 0) or 0), 3),
                           "size_mb": round(int(fmt.get("size", 0) or 0) / 1e6, 2), "format": fmt.get("format_name")}
    vids = _streams(info, "video")
    if vids:
        v = vids[0]
        out.update(width=v.get("width"), height=v.get("height"), fps=_fps(v), video_codec=v.get("codec_name"))
    auds = _streams(info, "audio")
    out["audio"] = [{"codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"),
                     "channels": a.get("channels")} for a in auds] or None
    return json.dumps(out, ensure_ascii=False, indent=1)


def video_trim(path: str, start: float, end: float, out: str | None = None) -> str:
    src = _check(path)
    if end <= start:
        raise ValueError("end must be greater than start")
    o = _out_path(src, f"trim_{start:g}-{end:g}", out)
    _run_ffmpeg(["-ss", str(start), "-to", str(end), "-i", str(src), *_encode_args(), str(o)])
    return _done(o)


def video_concat(paths: list[str], out: str) -> str:
    if len(paths) < 2:
        raise ValueError("need at least 2 videos")
    srcs = [_check(p) for p in paths]
    first = _probe(str(srcs[0]))
    v0 = _streams(first, "video")[0]
    w, h, fps = int(v0["width"]), int(v0["height"]), _fps(v0)
    args: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    n_in = 0
    for i, s in enumerate(srcs):
        args += ["-i", str(s)]
        filters.append(f"[{n_in}:v]{_fit_filter(w, h, 'pad')},fps={fps},format=yuv420p[v{i}]")
        if _has_audio(str(s)):
            filters.append(f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
            n_in += 1
        else:
            args += ["-f", "lavfi", "-t", f"{_duration(str(s)):.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            filters.append(f"[{n_in + 1}:a]anull[a{i}]")
            n_in += 2
        labels.append(f"[v{i}][a{i}]")
    filters.append(f"{''.join(labels)}concat=n={len(srcs)}:v=1:a=1[v][a]")
    o = _out_path(srcs[0], "concat", out)
    _run_ffmpeg([*args, "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]", *_encode_args(), str(o)])
    return _done(o, f"joined {len(srcs)} clips at {w}x{h}@{fps}")


def detect_silences(path: str, noise_db: float = -30, min_silence: float = 0.5) -> list[tuple[float, float]]:
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", path, "-vn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    if len(ends) < len(starts):  # silence runs to the end of file
        ends.append(_duration(path))
    return list(zip(starts, ends))


def video_cut_silence(path: str, out: str | None = None, noise_db: float = -30,
                      min_silence: float = 0.5, padding: float = 0.15) -> str:
    src = _check(path)
    if not _has_audio(str(src)):
        raise ValueError("video has no audio track; nothing to detect")
    total = _duration(str(src))
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in detect_silences(str(src), noise_db, min_silence):
        seg_end = min(total, s + padding)
        if seg_end - cursor > 0.05:
            keep.append((cursor, seg_end))
        cursor = max(cursor, e - padding)
    if total - cursor > 0.05:
        keep.append((cursor, total))
    if not keep:
        raise ValueError("no speech segments detected; lower noise_db (e.g. -40)")
    parts = []
    for i, (s, e) in enumerate(keep):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}];"
                     f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
    parts.append("".join(f"[v{i}][a{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=1:a=1[v][a]")
    o = _out_path(src, "nosilence", out)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(";\n".join(parts))
        script = f.name
    try:
        _run_ffmpeg(["-i", str(src), "-filter_complex_script", script, "-map", "[v]", "-map", "[a]",
                     *_encode_args(), str(o)])
    finally:
        os.unlink(script)
    kept = ", ".join(f"{s:.2f}-{e:.2f}" for s, e in keep)
    return _done(o, f"kept {len(keep)} segments (of {total:.2f}s): {kept}")


def video_chromakey(path: str, background: str, out: str | None = None, color: str = "0x00FF00",
                    similarity: float = 0.3, blend: float = 0.1) -> str:
    src = _check(path)
    v0 = _streams(_probe(str(src)), "video")[0]
    w, h, fps = int(v0["width"]), int(v0["height"]), _fps(v0)
    dur = _duration(str(src))
    bg = background.strip()
    if bg.startswith("#") or re.fullmatch(r"(0x)?[0-9a-fA-F]{6}", bg) or (bg.isalpha() and not Path(bg).exists()):
        c = "0x" + bg[1:] if bg.startswith("#") else bg
        bg_args = ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"color=c={c}:s={w}x{h}:r={fps}"]
    else:
        bg_path = _check(bg)
        if bg_path.suffix.lower() in IMAGE_EXT:
            bg_args = ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(bg_path)]
        else:
            bg_args = ["-stream_loop", "-1", "-i", str(bg_path)]
    fc = (f"[1:v]{_fit_filter(w, h, 'crop')},fps={fps},format=yuv420p[bg];"
          f"[0:v]chromakey={color}:{similarity}:{blend}[fg];"
          f"[bg][fg]overlay=shortest=1:format=auto,format=yuv420p[v]")
    o = _out_path(src, "keyed", out)
    maps = ["-map", "[v]"] + (["-map", "0:a"] if _has_audio(str(src)) else [])
    _run_ffmpeg(["-i", str(src), *bg_args, "-filter_complex", fc, *maps, "-shortest", *_encode_args(), str(o)])
    return _done(o)


def video_add_music(path: str, music_path: str, out: str | None = None, music_volume: float = 0.15,
                    duck: bool = True) -> str:
    src, music = _check(path), _check(music_path)
    dur = _duration(str(src))
    fade_start = max(0.0, dur - 2.0)
    music_chain = f"[1:a]volume={music_volume},aresample=48000,aformat=channel_layouts=stereo[m]"
    if _has_audio(str(src)):
        if duck:
            fc = (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit[voice][sc];{music_chain};"
                  f"[m][sc]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=500:makeup=1[md];"
                  f"[voice][md]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fade_start:.3f}:d=2[a]")
        else:
            fc = (f"[0:a]aresample=48000,aformat=channel_layouts=stereo[voice];{music_chain};"
                  f"[voice][m]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fade_start:.3f}:d=2[a]")
    else:
        fc = f"{music_chain};[m]atrim=0:{dur:.3f},afade=t=out:st={fade_start:.3f}:d=2[a]"
    o = _out_path(src, "music", out)
    _run_ffmpeg(["-i", str(src), "-stream_loop", "-1", "-i", str(music), "-filter_complex", fc,
                 "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{dur:.3f}", "-movflags", "+faststart", str(o)])
    return _done(o)


def video_resize(path: str, preset: str = "9:16", out: str | None = None, mode: str = "crop") -> str:
    src = _check(path)
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {list(PRESETS)}")
    if mode not in ("crop", "pad"):
        raise ValueError("mode must be 'crop' or 'pad'")
    w, h = PRESETS[preset]
    o = _out_path(src, f"{w}x{h}", out)
    _run_ffmpeg(["-i", str(src), "-vf", _fit_filter(w, h, mode), *_encode_args(), str(o)])
    return _done(o, f"{preset} -> {w}x{h} ({mode})")


def video_captions(path: str, srt_path: str, out: str | None = None, fontsize: int = 16,
                   outline: int = 2, margin: int = 60, font: str = "") -> str:
    src, srt = _check(path), _check(srt_path)
    style = f"FontSize={fontsize},Outline={outline},MarginV={margin},Bold=1,PrimaryColour=&H00FFFFFF"
    if font:
        style += f",FontName={font}"
    vf = f"subtitles='{_fesc(str(srt))}':force_style='{style}'"
    o = _out_path(src, "sub", out)
    try:
        _run_ffmpeg(["-i", str(src), "-vf", vf, *_encode_args(), str(o)])
    except RuntimeError as e:
        if "No such filter" in str(e) or "libass" in str(e):
            raise RuntimeError("this ffmpeg build lacks the libass 'subtitles' filter; "
                               "install a full ffmpeg build to burn captions") from e
        raise
    return _done(o)


def video_transcribe(path: str, model: str = "small", language: str = "vi", out: str | None = None) -> str:
    src = _check(path)
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError:
        return ("faster-whisper is not installed. Install it with: pip install faster-whisper "
                "(then call video_transcribe again). Alternative: write the SRT by hand and use video_captions.")
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _ = wm.transcribe(str(src), language=language, vad_filter=True)
    segs = [(float(s.start), float(s.end), s.text) for s in segments]
    srt = Path(out).expanduser() if out else src.with_suffix(".srt")
    write_srt(segs, str(srt))
    preview = "\n".join(t.strip() for _, _, t in segs[:8])
    return f"OK -> {srt} ({len(segs)} segments)\n{preview}"


def video_extract_audio(path: str, out: str | None = None) -> str:
    src = _check(path)
    o = _out_path(src, "audio", out, ext=".mp3")
    _run_ffmpeg(["-i", str(src), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(o)])
    return _done(o)


def video_thumbnail(path: str, time: float = 0.0, out: str | None = None) -> str:
    src = _check(path)
    o = _out_path(src, f"thumb_{time:g}s", out, ext=".jpg")
    _run_ffmpeg(["-ss", str(time), "-i", str(src), "-frames:v", "1", "-q:v", "2", str(o)])
    return f"OK -> {o}"


def _atempo_chain(factor: float) -> str:
    parts: list[str] = []
    while factor > 2.0:
        parts.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        parts.append("atempo=0.5")
        factor /= 0.5
    parts.append(f"atempo={factor:.4f}")
    return ",".join(parts)


def video_speed(path: str, factor: float, out: str | None = None) -> str:
    src = _check(path)
    if factor <= 0:
        raise ValueError("factor must be > 0")
    o = _out_path(src, f"x{factor:g}", out)
    fc = f"[0:v]setpts=PTS/{factor}[v]"
    maps = ["-map", "[v]"]
    if _has_audio(str(src)):
        fc += f";[0:a]{_atempo_chain(factor)}[a]"
        maps += ["-map", "[a]"]
    _run_ffmpeg(["-i", str(src), "-filter_complex", fc, *maps, *_encode_args(), str(o)])
    return _done(o)


def video_add_text(path: str, text: str, out: str | None = None, position: str = "bottom", fontsize: int = 56,
                   color: str = "white", start: float = 0.0, end: float | None = None) -> str:
    src = _check(path)
    ys = {"top": "h*0.08", "center": "(h-text_h)/2", "bottom": "h*0.85-text_h"}
    if position not in ys:
        raise ValueError("position must be top|center|bottom")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        tf = f.name
    opts = [f"textfile='{_fesc(tf)}'", f"fontsize={fontsize}", f"fontcolor={color}", "x=(w-text_w)/2",
            f"y={ys[position]}", "box=1", "boxcolor=black@0.45", "boxborderw=14", "line_spacing=8"]
    font = _find_font()
    if font:
        opts.append(f"fontfile='{_fesc(font)}'")
    end_t = end if end is not None else _duration(str(src))
    opts.append(f"enable='between(t,{start},{end_t})'")
    o = _out_path(src, "text", out)
    try:
        _run_ffmpeg(["-i", str(src), "-vf", "drawtext=" + ":".join(opts), "-c:a", "copy",
                     *_vencode_args(), "-movflags", "+faststart", str(o)])
    finally:
        os.unlink(tf)
    return _done(o, f"font: {font or 'ffmpeg default'}")


# --- registry ---------------------------------------------------------------
def _s(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


P = {"path": {"type": "string", "description": "Input video path"},
     "out": {"type": "string", "description": "Output path (default: next to input with a suffix)"}}

TOOLS: list[Tool] = [
    Tool("video_info", "Show duration, resolution, fps, codecs and audio streams of a media file.",
         _s({"path": P["path"]}, ["path"]), video_info, tags=["video"]),
    Tool("video_trim", "Cut a video between start and end seconds.",
         _s({**P, "start": {"type": "number"}, "end": {"type": "number"}}, ["path", "start", "end"]),
         video_trim, tags=["video"]),
    Tool("video_concat", "Join several videos in order (re-encoded to the size/fps of the first clip).",
         _s({"paths": {"type": "array", "items": {"type": "string"}}, "out": P["out"]}, ["paths", "out"]),
         video_concat, tags=["video"]),
    Tool("video_cut_silence", "Remove silent gaps (filler pauses) from a talking-head video, keeping speech.",
         _s({**P, "noise_db": {"type": "number", "description": "Silence threshold dB (default -30)"},
             "min_silence": {"type": "number", "description": "Min silence length seconds (default 0.5)"},
             "padding": {"type": "number", "description": "Seconds kept around speech (default 0.15)"}}, ["path"]),
         video_cut_silence, tags=["video"]),
    Tool("video_chromakey", "Replace a green (or other) screen with an image, video or solid color like '#1e3a5f'.",
         _s({**P, "background": {"type": "string"}, "color": {"type": "string", "description": "Key color, default 0x00FF00"},
             "similarity": {"type": "number"}, "blend": {"type": "number"}}, ["path", "background"]),
         video_chromakey, tags=["video"]),
    Tool("video_add_music", "Mix background music under the voice (looped, faded out, ducked under speech).",
         _s({**P, "music_path": {"type": "string"}, "music_volume": {"type": "number", "description": "0-1, default 0.15"},
             "duck": {"type": "boolean", "description": "Lower music while speaking (default true)"}},
            ["path", "music_path"]), video_add_music, tags=["video"]),
    Tool("video_resize", "Resize/crop to a social preset: 9:16 (1080x1920), 16:9 (1920x1080) or 1:1 (1080x1080).",
         _s({**P, "preset": {"type": "string", "enum": list(PRESETS)}, "mode": {"type": "string", "enum": ["crop", "pad"]}},
            ["path", "preset"]), video_resize, tags=["video"]),
    Tool("video_captions", "Burn an SRT subtitle file into the video.",
         _s({**P, "srt_path": {"type": "string"}, "fontsize": {"type": "integer"}, "outline": {"type": "integer"},
             "margin": {"type": "integer", "description": "Bottom margin px"}, "font": {"type": "string"}},
            ["path", "srt_path"]), video_captions, tags=["video"]),
    Tool("video_transcribe", "Transcribe speech to an SRT file with faster-whisper (Vietnamese by default).",
         _s({**P, "model": {"type": "string", "description": "tiny|base|small|medium|large-v3"},
             "language": {"type": "string"}}, ["path"]), video_transcribe, tags=["video"]),
    Tool("video_extract_audio", "Extract the audio track to MP3.", _s(P, ["path"]), video_extract_audio, tags=["video"]),
    Tool("video_thumbnail", "Save one frame as a JPG at the given time (seconds).",
         _s({**P, "time": {"type": "number"}}, ["path"]), video_thumbnail, tags=["video"]),
    Tool("video_speed", "Change playback speed (factor 2 = twice as fast, 0.5 = half).",
         _s({**P, "factor": {"type": "number"}}, ["path", "factor"]), video_speed, tags=["video"]),
    Tool("video_add_text", "Overlay a text title (with a dark box) at top/center/bottom for a time range.",
         _s({**P, "text": {"type": "string"}, "position": {"type": "string", "enum": ["top", "center", "bottom"]},
             "fontsize": {"type": "integer"}, "color": {"type": "string"}, "start": {"type": "number"},
             "end": {"type": "number"}}, ["path", "text"]), video_add_text, tags=["video"]),
]

__all__ = ["TOOLS", "write_srt", "detect_silences", *[t.name for t in TOOLS]]
