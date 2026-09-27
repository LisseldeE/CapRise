"""
录屏
全屏录制：WGC 抓帧 + 严格 CFR 定速 + 硬件优先 H.264 编码
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import ctypes
import threading
import time
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import QObject, Signal

FPS = 60      # 输出恒定帧率
MONITOR = 1   # 1 = 主显示器（Windows 显示器序号从 1 开始）

RECORD_DIR = Path.home() / "CapRise" / "recordings"

# 编码器优先级：软件 x264 在 2K60 下吃不住实时，先试硬件编码，逐个回退
ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf", "libx264")

# 恒定质量参数，不锁码率；画质与速度按录屏场景取舍
ENCODER_OPTS = {
    "libx264": {"crf": "18", "preset": "veryfast", "tune": "stillimage"},
    "h264_nvenc": {"rc": "vbr", "cq": "19", "preset": "p5", "tune": "hq"},
    "h264_qsv": {"preset": "veryfast", "global_quality": "19", "look_ahead": "0"},
    "h264_amf": {"rc": "cqp", "qp_i": "20", "qp_p": "22", "qp_b": "22",
                 "quality": "speed"},
}


def _timer_begin(ms):
    """把系统定时器精度提到 1ms，否则 Sleep 粒度约 15ms 会打乱 60fps 节拍。"""
    try:
        ctypes.windll.winmm.timeBeginPeriod(ms)
        return True
    except Exception:
        return False


def _timer_end(ms):
    try:
        ctypes.windll.winmm.timeEndPeriod(ms)
    except Exception:
        pass


class ScreenRecorder(QObject):
    """全屏录制。

    采集线程由 windows-capture 负责，本类只做两件事：把回调里的帧拷成
    最新帧槽（原生缓冲仅在回调内有效），再在编码线程里按墙钟节拍逐帧写
    出。WGC 是变帧率的，只有严格 CFR 才能得到时长与帧率都正确的成片。
    """

    started = Signal()
    finished = Signal(str)   # 成片路径
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._latest = None
        self._capture = None
        self._control = None
        self._thread = None
        self._stop_requested = False
        self._path = None
        self._error = None
        self._timer = False
        # 统计（跨线程累加，仅用于实测报告）
        self._encoder = ""
        self._captured = 0
        self._used = 0
        self._encoded = 0
        self._late = 0    # 落后于节拍的次数
        self._stalls = 0  # 严重滞后后重锚的次数

    # ----- lifecycle -----
    def is_recording(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, path=None):
        if self.is_recording():
            return False
        try:
            import av  # noqa: F401
            from windows_capture import WindowsCapture
        except Exception as e:
            self.failed.emit(f"缺少录屏依赖：{e}")
            return False

        self._latest = None
        self._stop_requested = False
        self._error = None
        self._captured = self._used = self._encoded = 0
        self._late = self._stalls = 0
        self._encoder = ""
        self._path = Path(path) if path else self._default_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

        capture = WindowsCapture(
            monitor_index=MONITOR, cursor_capture=True, draw_border=False
        )

        @capture.event
        def on_frame_arrived(frame, capture_control):
            buf = frame.frame_buffer
            # 必须拷贝：frame_buffer 是原生缓冲的视图，回调返回后即失效
            with self._lock:
                self._latest = buf.copy()
                self._captured += 1

        @capture.event
        def on_closed():
            # 采集被系统主动结束（如显示器断开），按停止处理以便收尾成片
            self._stop_requested = True

        self._capture = capture  # 保持引用，否则 Rust 侧回调会被回收
        try:
            self._control = capture.start_free_threaded()
        except Exception as e:
            self._capture = None
            self.failed.emit(f"启动采集失败：{e}")
            return False

        self._timer = _timer_begin(1)
        self._thread = threading.Thread(
            target=self._encode_loop, name="CapRiseRecorder", daemon=True
        )
        self._thread.start()
        self.started.emit()
        return True

    def stop(self):
        """停止录制并收尾文件，返回统计信息（未在录则返回 None）。"""
        if not self.is_recording():
            return None
        self._stop_requested = True
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:
                pass
        self._thread.join(timeout=10)
        self._thread = None
        self._control = None
        self._capture = None
        if self._timer:
            _timer_end(1)
            self._timer = False

        if self._error:
            self.failed.emit(self._error)
        elif self._encoded:
            self.finished.emit(str(self._path))
        else:
            self._error = "未捕获到任何画面"
            self.failed.emit(self._error)
        return self.stats()

    def stats(self):
        path = Path(self._path) if self._path else None
        size = path.stat().st_size if path and path.exists() else 0
        return {
            "path": str(path) if path else "",
            "encoder": self._encoder,
            "encoded": self._encoded,
            "captured": self._captured,
            "used": self._used,
            "dup": self._encoded - self._used,
            "late": self._late,
            "stalls": self._stalls,
            "video_seconds": round(self._encoded / FPS, 2),
            "size_mb": round(size / 1048576, 1),
            "error": self._error or "",
        }

    # ----- encoder -----
    def _default_path(self):
        name = time.strftime("CapRise_%Y%m%d_%H%M%S.mp4")
        return RECORD_DIR / name

    def _take_latest(self):
        """取走最新帧；无新帧返回 None（静态画面时 WGC 本来就不出帧）。"""
        with self._lock:
            buf = self._latest
            self._latest = None
        return buf

    def _open_writer(self, av, name, w, h):
        container = av.open(str(self._path), mode="w", format="mp4")
        stream = container.add_stream(name, rate=FPS)
        stream.width, stream.height = w, h
        stream.pix_fmt = "yuv420p"
        stream.options = dict(ENCODER_OPTS[name])
        return container, stream

    def _discard(self, container):
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
        return None, None

    def _write(self, av, container, stream, buf, pts):
        frame = self._to_frame(av, buf, stream)
        frame.pts = pts
        frame.time_base = Fraction(1, FPS)
        for packet in stream.encode(frame):
            container.mux(packet)
        self._encoded += 1

    def _encode_loop(self):
        import av

        period = 1.0 / FPS
        container = stream = None
        cur = None
        pts = 0
        try:
            # 首帧没到就不知道分辨率，先等
            while not self._stop_requested and cur is None:
                cur = self._take_latest()
                if cur is None:
                    time.sleep(0.005)
            if cur is None:
                return
            h = cur.shape[0] - cur.shape[0] % 2  # yuv420p 要求宽高为偶数
            w = cur.shape[1] - cur.shape[1] % 2
            # 逐个试：硬件缺失或参数不支持都在首帧编码这一步抛错，直接换下一个
            for name in ENCODERS:
                try:
                    container, stream = self._open_writer(av, name, w, h)
                    self._write(av, container, stream, cur, 0)
                    self._encoder = name
                    pts = 1
                    break
                except Exception as e:
                    self._error = f"{name} 不可用：{e}"
                    container, stream = self._discard(container)
            if stream is None:
                return
            self._error = None

            t0 = time.monotonic()
            while not self._stop_requested:
                new = self._take_latest()
                if new is not None:
                    cur = new
                    self._used += 1
                # 帧号由单调时钟推算：落后就用重复帧补齐，成片时长与录制时长一致
                tick = int((time.monotonic() - t0) * FPS + 0.5)
                if tick > pts + FPS:
                    t0 = time.monotonic() - pts * period  # 卡顿后重锚，不补大量重复帧
                    tick = pts
                    self._stalls += 1
                if tick - pts > 1:
                    self._late += 1
                while pts <= tick:
                    self._write(av, container, stream, cur, pts)
                    pts += 1
                rem = t0 + pts * period - time.monotonic()
                if rem > 0.0005:
                    time.sleep(rem)
        except Exception as e:
            self._error = f"录制中断：{e}"
        finally:
            if stream is not None:
                try:
                    for packet in stream.encode():  # 冲刷编码器
                        container.mux(packet)
                except Exception as e:
                    self._error = self._error or f"收尾失败：{e}"
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass

    def _to_frame(self, av, buf, stream):
        """BGRA 缓冲转编码帧；分辨率中途变化时缩放回录制尺寸。"""
        if (buf.shape[1], buf.shape[0]) != (stream.width, stream.height):
            frame = av.VideoFrame.from_ndarray(buf, format="bgra")
            return frame.reformat(
                width=stream.width, height=stream.height, format="bgra"
            )
        return av.VideoFrame.from_ndarray(buf, format="bgra")