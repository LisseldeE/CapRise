"""
录屏
全屏录制：WGC 抓帧 + 严格 CFR 定速 + 硬件优先 H.264 编码
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import ctypes
import sys
import threading
import time
import types
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from modules.config import Config

# 打包排除了 cv2（windows_capture 顶层 import 它但录制路径不用），缺失时补空桩。
try:
    import cv2  # noqa: F401
except ImportError:
    sys.modules.setdefault("cv2", types.ModuleType("cv2"))

FPS = 60      # 输出恒定帧率
MONITOR = 1   # 1 = 主显示器（Windows 显示器序号从 1 开始）

# 默认保存目录：设置页「录制」分类可改，改后写进 config.json
DEFAULT_RECORD_DIR = Path.home() / "CapRise" / "recordings"

# 编码器优先级：软件 x264 在 2K60 下吃不住实时，先试硬件编码，逐个回退
ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf", "libx264")

# 探测出来的可用编码器（prewarm 在后台填，None = 还没探到）
_PREFERRED = None

# 录制已经开跑：探测让路，别和它要保护的展开动画抢 GUI
_PROBE_ABORT = threading.Event()

# 恒定质量参数，不锁码率；画质与速度按录屏场景取舍
ENCODER_OPTS = {
    "libx264": {"crf": "18", "preset": "veryfast", "tune": "stillimage"},
    "h264_nvenc": {"rc": "vbr", "cq": "19", "preset": "p5", "tune": "hq"},
    "h264_qsv": {"preset": "veryfast", "global_quality": "19", "look_ahead": "0"},
    "h264_amf": {"rc": "cqp", "qp_i": "20", "qp_p": "22", "qp_b": "22",
                 "quality": "speed"},
}


def record_dir():
    """录制保存目录（设置页可改，存 config.json，未设置时用默认目录）。"""
    saved = Config().get("record_dir")
    return Path(saved) if saved else DEFAULT_RECORD_DIR


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


def _probe_encoder():
    """挨个试编码器，返回第一个真能用的名字（全不可用返回 None）。

    必须在这里探、而且要把结果留着：不可用的硬件编码器在"失败"之前会真去
    初始化厂商运行时（nvEncodeAPI / MFX / AMF），在 PyAV 里这段是占着 GIL 的
    阻塞调用 —— 实测能把 GUI 冻住约 100ms。放在点录制的那一刻做，正好撞在
    胶囊栏展开动画上：展开到一半卡住，剩下的宽度连停止按钮一起一次蹦完。

    用 1 帧 64×64 探：硬件缺失、参数不支持都在首帧编码这一步抛错，与真实
    2K 帧走的是同一条初始化路径。产物扔进 BytesIO，不落盘。"""
    global _PREFERRED
    try:
        import io
        import av
    except Exception:
        return None
    for name in ENCODERS:
        if _PROBE_ABORT.is_set():
            return None
        container = None
        try:
            container = av.open(io.BytesIO(), mode="w", format="mp4")
            stream = container.add_stream(name, rate=1)
            stream.width, stream.height = 64, 64
            stream.pix_fmt = "yuv420p"
            stream.options = dict(ENCODER_OPTS[name])
            stream.encode(av.VideoFrame(64, 64, "yuv420p"))
            stream.encode(None)
            container.close()
            _PREFERRED = name
            return name
        except Exception:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass
    return None


def prewarm():
    """后台预热录屏依赖，并把可用的编码器探出来。

    `av` 首次 import 要加载 FFmpeg 那批 DLL、`windows_capture` 是 Rust 扩展，
    实测冷启动合计约 143ms。若等到用户点录制时才导，这段（外加建 D3D11 设备 /
    WGC 会话的 125~171ms）就整段顶在 GUI 线程上，界面要等它走完才开始动 ——
    看着就是"点了没反应、然后突然跳一下"。所以建对象时先导掉。

    编码器探测同理，但它本身还要再耗 100ms 左右，所以先让启动那阵忙过去。"""
    try:
        import av  # noqa: F401
        from windows_capture import WindowsCapture  # noqa: F401
    except Exception:
        return
    time.sleep(1.2)
    _probe_encoder()


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
        self._thread = None         # 编码线程
        self._start_thread = None   # 启动线程（导入依赖 + 建采集会话）
        self._starting = False      # 启动进行中：这期间 is_recording() 也算在录
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
        # 依赖在后台先导掉，别留到第一次点录制时才在 GUI 线程上导
        threading.Thread(target=prewarm, name="CapRiseRecorderPrewarm",
                         daemon=True).start()

    # ----- lifecycle -----
    def is_recording(self):
        if self._starting:
            return True
        return self._thread is not None and self._thread.is_alive()

    def start(self, path=None):
        if self.is_recording():
            return False
        _PROBE_ABORT.set()
        self._latest = None
        self._stop_requested = False
        self._error = None
        self._captured = self._used = self._encoded = 0
        self._late = self._stalls = 0
        self._encoder = ""
        self._path = Path(path) if path else self._default_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # 采集侧初始化（导入依赖 + 建 D3D11 设备 / WGC 会话，实测合计 130~320ms）
        # 整段丢给工作线程，GUI 线程立刻把界面点亮并返回：否则状态条出现、按钮
        # 点亮、宽度动画都要干等这段时间，看着就是"点了没反应、然后突然跳一下"。
        self._starting = True
        self._start_thread = threading.Thread(
            target=self._begin_capture, name="CapRiseRecorderStart", daemon=True
        )
        self._start_thread.start()
        self.started.emit()
        return True

    def _begin_capture(self):
        """工作线程：导入依赖 → 建采集会话 → 起编码线程。

        `started` 在 start() 里就已发出（界面即时响应），所以这里只负责把采集
        真正拉起来；中途被叫停（_stop_requested）的会话就地收掉，不能留给
        stop()，那时它已经以为没有控制对象可停了。"""
        try:
            import av  # noqa: F401
            from windows_capture import WindowsCapture
        except Exception as e:
            self._starting = False
            self.failed.emit(f"缺少录屏依赖：{e}")
            return

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
            control = capture.start_free_threaded()
        except Exception as e:
            self._capture = None
            self._starting = False
            self.failed.emit(f"启动采集失败：{e}")
            return
        self._control = control
        if self._stop_requested:
            # 点完录制马上又点停止：会话刚建好，就地收掉
            try:
                control.stop()
            except Exception:
                pass
            self._control = None
            self._capture = None
            self._starting = False
            return

        self._timer = _timer_begin(1)
        self._thread = threading.Thread(
            target=self._encode_loop, name="CapRiseRecorder", daemon=True
        )
        self._thread.start()
        self._starting = False

    def stop(self):
        """停止录制并收尾文件，返回统计信息（未在录则返回 None）。"""
        if not self.is_recording():
            return None
        self._stop_requested = True
        # 采集还没建好就先等它落地：否则那个会话刚建好却没人叫停，会一直录
        if self._start_thread is not None and self._start_thread.is_alive():
            self._start_thread.join(timeout=3)
        self._start_thread = None
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:
                pass
        if self._thread is not None:
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
        return record_dir() / name

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
        global _PREFERRED
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
            # 先试 prewarm 探到的那个（已经初始化过，再开一次几乎不花时间），
            # 其余照旧作为回退：硬件缺失或参数不支持都在首帧编码这一步抛错。
            order = list(ENCODERS)
            if _PREFERRED:
                order.remove(_PREFERRED)
                order.insert(0, _PREFERRED)
            for name in order:
                try:
                    container, stream = self._open_writer(av, name, w, h)
                    self._write(av, container, stream, cur, 0)
                    self._encoder = name
                    _PREFERRED = name     # 这次挑中的记下来，下一次直接从它开始
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