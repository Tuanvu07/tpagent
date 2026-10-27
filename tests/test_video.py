"""ffmpeg-backed video tools, exercised on a generated 3-second test clip."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tpagent.tools import video as V

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") and not Path(V.FFMPEG).exists(),
                                reason="ffmpeg not available")


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """3s 640x360 clip: tone 0-1s, silence 1-2s, tone 2-3s."""
    out = tmp_path_factory.mktemp("vid") / "raw.mp4"
    audio = "sine=frequency=440:sample_rate=48000,volume='if(between(t,1,2),0,1)':eval=frame"
    subprocess.run([V.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
                    "-f", "lavfi", "-i", audio, "-t", "3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
    return out


def _dur(path: str) -> float:
    return json.loads(V.video_info(path))["duration"]


def test_info(clip: Path) -> None:
    info = json.loads(V.video_info(str(clip)))
    assert info["width"] == 640 and info["height"] == 360
    assert 2.9 <= info["duration"] <= 3.2
    assert info["audio"] and info["audio"][0]["codec"] == "aac"
    assert info["fps"] == 30


def test_trim(clip: Path) -> None:
    msg = V.video_trim(str(clip), 0.5, 2.0)
    out = clip.with_name("raw_trim_0.5-2.mp4")
    assert out.exists() and str(out) in msg
    assert 1.3 <= _dur(str(out)) <= 1.7


def test_never_overwrite_input(clip: Path) -> None:
    with pytest.raises(ValueError):
        V.video_trim(str(clip), 0, 1, out=str(clip))


def test_resize_crop_and_pad(clip: Path, tmp_path: Path) -> None:
    V.video_resize(str(clip), "9:16", out=str(tmp_path / "v.mp4"), mode="crop")
    info = json.loads(V.video_info(str(tmp_path / "v.mp4")))
    assert (info["width"], info["height"]) == (1080, 1920)
    V.video_resize(str(clip), "1:1", out=str(tmp_path / "sq.mp4"), mode="pad")
    info = json.loads(V.video_info(str(tmp_path / "sq.mp4")))
    assert (info["width"], info["height"]) == (1080, 1080)
    with pytest.raises(ValueError):
        V.video_resize(str(clip), "4:3")


def test_cut_silence(clip: Path, tmp_path: Path) -> None:
    out = tmp_path / "cut.mp4"
    msg = V.video_cut_silence(str(clip), out=str(out), noise_db=-40, min_silence=0.4, padding=0.1)
    assert out.exists() and "kept 2 segments" in msg
    assert 1.9 <= _dur(str(out)) <= 2.5  # ~1s of silence removed (minus padding)


def test_add_text(clip: Path, tmp_path: Path) -> None:
    out = tmp_path / "text.mp4"
    V.video_add_text(str(clip), "Cầm Đồ Thành Phát\nPhí 1.5%", out=str(out), position="bottom", start=0, end=2)
    assert out.exists() and 2.9 <= _dur(str(out)) <= 3.2
    with pytest.raises(ValueError):
        V.video_add_text(str(clip), "x", position="middle")


def test_concat_different_sizes(clip: Path, tmp_path: Path) -> None:
    small = tmp_path / "small.mp4"
    V.video_resize(str(clip), "1:1", out=str(small), mode="pad")
    out = tmp_path / "joined.mp4"
    msg = V.video_concat([str(clip), str(small)], str(out))
    assert out.exists() and "640x360" in msg
    assert 5.8 <= _dur(str(out)) <= 6.4


def test_thumbnail_and_extract_audio(clip: Path, tmp_path: Path) -> None:
    thumb = tmp_path / "t.jpg"
    V.video_thumbnail(str(clip), 1.0, out=str(thumb))
    assert thumb.exists() and thumb.stat().st_size > 1000
    mp3 = tmp_path / "a.mp3"
    V.video_extract_audio(str(clip), out=str(mp3))
    assert mp3.exists() and 2.8 <= _dur(str(mp3)) <= 3.3


def test_speed(clip: Path, tmp_path: Path) -> None:
    out = tmp_path / "fast.mp4"
    V.video_speed(str(clip), 3.0, out=str(out))
    assert 0.8 <= _dur(str(out)) <= 1.3


def test_chromakey_color_and_music(clip: Path, tmp_path: Path) -> None:
    keyed = tmp_path / "keyed.mp4"
    V.video_chromakey(str(clip), "#1e3a5f", out=str(keyed), similarity=0.2)
    assert 2.8 <= _dur(str(keyed)) <= 3.3
    music = tmp_path / "music.mp3"
    V.video_extract_audio(str(clip), out=str(music))
    mixed = tmp_path / "mixed.mp4"
    V.video_add_music(str(clip), str(music), out=str(mixed), duck=True)
    assert 2.8 <= _dur(str(mixed)) <= 3.3


def test_captions_and_srt(clip: Path, tmp_path: Path) -> None:
    srt = tmp_path / "c.srt"
    V.write_srt([(0.0, 1.5, "Xin chào"), (1.5, 3.0, "Cầm đồ Thành Phát")], str(srt))
    assert "00:00:01,500 --> 00:00:03,000" in srt.read_text(encoding="utf-8")
    out = tmp_path / "sub.mp4"
    V.video_captions(str(clip), str(srt), out=str(out))
    assert out.exists() and 2.8 <= _dur(str(out)) <= 3.3


def test_transcribe_without_whisper(clip: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    real_import = builtins.__import__

    def fake(name: str, *a: object, **k: object) -> object:
        if name == "faster_whisper":
            raise ImportError
        return real_import(name, *a, **k)  # type: ignore[arg-type]
    monkeypatch.setattr(builtins, "__import__", fake)
    assert "pip install faster-whisper" in V.video_transcribe(str(clip))


def test_registry() -> None:
    names = {t.name for t in V.TOOLS}
    assert {"video_info", "video_cut_silence", "video_chromakey", "video_resize"} <= names
    assert all(not t.dangerous and "video" in t.tags for t in V.TOOLS)
    with pytest.raises(FileNotFoundError):
        V.video_info("/nonexistent/x.mp4")
