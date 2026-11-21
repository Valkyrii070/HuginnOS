"""A module that's imported the first time it's used, for the big ones an app needs only now and then (OpenCV takes
half a second to import; Scan and Clips open without it and bring it in when a picture is first worked on).

    cv2 = Lazy("cv2")
    if cv2: ...            # False when it isn't installed
    cv2.warpPerspective(...)

`warm()` imports it in the background a moment after the window is up, so the first use doesn't wait either.
"""
import importlib
import threading


class Lazy:
    def __init__(self, name: str):
        self.__dict__["_name"] = name
        self.__dict__["_mod"] = None
        self.__dict__["_lock"] = threading.Lock()

    def _load(self):
        if self._mod is None:
            with self._lock:
                if self._mod is None:
                    try:
                        self.__dict__["_mod"] = importlib.import_module(self._name)
                    except ImportError:
                        self.__dict__["_mod"] = False
        return self._mod

    def __bool__(self) -> bool:
        return bool(self._load())

    def __getattr__(self, attr):
        mod = self._load()
        if not mod:
            raise ImportError(f"{self._name} isn't installed")
        return getattr(mod, attr)

    def warm(self, after: float = 1.5) -> None:
        t = threading.Timer(after, self._load)
        t.daemon = True
        t.start()
