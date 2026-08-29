"""Utility functions for FFmpeg synthesis and cross-platform path escaping."""

from pathlib import Path


def escape_ffmpeg_filter_path(path: Path | str) -> str:
    """
    Escape path for FFmpeg filter arguments (ass=..., subtitles=...).

    Cross-platform rules (Windows & Linux):
    1. Resolve absolute path;
    2. Convert backslashes '\\' to forward slashes '/';
    3. Escape colons ':' (e.g. C: -> C\\:);
    4. Escape single quotes '\'' -> '\\\'';
    5. Escape brackets '[' ']' -> '\\[' '\\]'.
    """
    path_str = str(Path(path).resolve())
    # 1. Normalize backslashes to forward slashes
    path_str = path_str.replace("\\", "/")
    # 2. Escape colons (especially for Windows drive letters like C:/)
    path_str = path_str.replace(":", r"\:")
    # 3. Escape single quotes
    path_str = path_str.replace("'", r"\'")
    # 4. Escape square brackets
    path_str = path_str.replace("[", r"\[").replace("]", r"\]")
    return path_str
