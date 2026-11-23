"""Exercise HLS seek and resume through the same libmpv that goes into the DMG."""

import ctypes as c
import functools
import http.server
import subprocess
import sys
import tempfile
import threading
import time


def check_playback(library, url):
    mpv = c.CDLL(library)
    mpv.mpv_create.restype = c.c_void_p
    mpv.mpv_set_option_string.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p]
    mpv.mpv_initialize.argtypes = [c.c_void_p]
    mpv.mpv_command.argtypes = [c.c_void_p, c.POINTER(c.c_char_p)]
    mpv.mpv_get_property.argtypes = [c.c_void_p, c.c_char_p, c.c_int, c.c_void_p]
    mpv.mpv_terminate_destroy.argtypes = [c.c_void_p]
    mpv.mpv_terminate_destroy.restype = None
    player = mpv.mpv_create()
    if not player:
        raise RuntimeError("mpv_create failed")

    def check(result):
        if result < 0:
            raise RuntimeError(f"libmpv returned {result}")

    def command(*args):
        check(mpv.mpv_command(player, (c.c_char_p * (len(args) + 1))(*args, None)))

    def wait_for_position(label, minimum, maximum):
        deadline = time.monotonic() + 30
        position = c.c_double()
        while time.monotonic() < deadline:
            # MPV_FORMAT_DOUBLE
            result = mpv.mpv_get_property(player, b"time-pos", 5, c.byref(position))
            if result >= 0 and minimum <= position.value <= maximum:
                print(f"{label}: playback reached {position.value:.2f}s", flush=True)
                return
            time.sleep(0.1)
        raise RuntimeError(f"{label}: playback did not reach {minimum}s ({position.value:.2f}s)")

    try:
        for option, value in {
            b"config": b"no",
            b"vo": b"null",
            b"ao": b"null",
            b"demuxer-max-bytes": b"150MiB",
            b"stream-lavf-o": b"reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,reconnect_delay_max=15",
        }.items():
            check(mpv.mpv_set_option_string(player, option, value))
        check(mpv.mpv_initialize(player))
        command(b"loadfile", url)
        wait_for_position("start", 2, 5)
        command(b"seek", b"18", b"absolute+exact")
        wait_for_position("seek", 20, 23)
        command(b"loadfile", url, b"replace", b"-1", b"start=30")
        wait_for_position("resume", 32, 35)
    finally:
        mpv.mpv_terminate_destroy(player)


with tempfile.TemporaryDirectory() as directory:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24",
        "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "42", "-c:v", "libx264", "-preset", "ultrafast", "-g", "144",
        "-c:a", "aac", "-f", "hls", "-hls_segment_type", "fmp4",
        "-hls_time", "6", "-hls_playlist_type", "vod", f"{directory}/index.m3u8",
    ], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            check_playback(sys.argv[1], f"http://127.0.0.1:{server.server_port}/index.m3u8".encode())
        finally:
            server.shutdown()
