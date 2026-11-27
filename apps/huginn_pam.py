"""Checking a person's own password through PAM, for Huginn's lock screen in its own compositor's session (KDE's
screen locker does this itself in the KWin session). It runs as the person, not root: pam_unix then asks its small
setgid helper, unix_chkpwd, which only ever answers for the person who's asking.

    check(user, password, service="huginn-lock") → (ok: bool, message: str)

Uses libpam through ctypes, so nothing has to be installed beyond PAM itself. The service is /etc/pam.d/huginn-lock.
"""
import ctypes
import ctypes.util
import threading

PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON, PAM_ERROR_MSG, PAM_TEXT_INFO = 1, 2, 3, 4
PAM_SUCCESS, PAM_AUTH_ERR, PAM_REFRESH_CRED = 0, 7, 0x0010
SAYS = {7: "Wrong password.", 9: "The password can't be checked right now.", 10: "That user can't be checked here.",
        13: "This account has expired.", 12: "This account isn't allowed to sign in now.", 20: "The password has expired."}


class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class PamResponse(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(PamMessage)),
                        ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)


class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV), ("appdata_ptr", ctypes.c_void_p)]


_lib = None
_lock = threading.Lock()


def _libs():
    global _lib
    if _lib is None:
        pam = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        libc.calloc.restype = ctypes.c_void_p
        libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
        libc.strdup.restype = ctypes.c_void_p
        libc.strdup.argtypes = [ctypes.c_char_p]
        pam.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(PamConv), ctypes.POINTER(ctypes.c_void_p)]
        pam.pam_authenticate.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_acct_mgmt.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_setcred.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_strerror.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_strerror.restype = ctypes.c_char_p
        _lib = (pam, libc)
    return _lib


def check(user: str, password: str, service: str = "huginn-lock") -> tuple:
    """Whether `password` is `user`'s, by PAM (the person's own account rules apply too). Takes about two seconds
    when it's wrong: PAM waits a little on purpose."""
    pam, libc = _libs()
    secret = password.encode("utf-8")
    said = []

    def conv(n, messages, responses, _data):
        replies = libc.calloc(n, ctypes.sizeof(PamResponse))       # PAM frees these itself
        if not replies:
            return 5                                              # PAM_BUF_ERR
        out = ctypes.cast(replies, ctypes.POINTER(PamResponse))
        for i in range(n):
            m = messages[i].contents
            if m.msg_style in (PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON):
                out[i].resp = libc.strdup(secret)
            elif m.msg and m.msg_style in (PAM_ERROR_MSG, PAM_TEXT_INFO):
                said.append(m.msg.decode("utf-8", "replace"))
        responses[0] = out
        return PAM_SUCCESS

    handle = ctypes.c_void_p()
    cb = CONV(conv)
    talk = PamConv(cb, None)
    with _lock:                                                    # libpam's modules aren't all thread-safe
        rc = pam.pam_start(service.encode(), user.encode(), ctypes.byref(talk), ctypes.byref(handle))
        if rc != PAM_SUCCESS:
            return False, "The password can't be checked right now."
        try:
            rc = pam.pam_authenticate(handle, 0)
            if rc == PAM_SUCCESS:
                rc = pam.pam_acct_mgmt(handle, 0)
            if rc == PAM_SUCCESS:
                pam.pam_setcred(handle, PAM_REFRESH_CRED)          # renews Kerberos tickets and the like, if any
        finally:
            pam.pam_end(handle, rc)
    if rc == PAM_SUCCESS:
        return True, ""
    return False, SAYS.get(rc, (said[-1] if said else "") or "Wrong password.")


# ------------------------------------------------------------------------------------------- a whole sign-in (root)
PAM_TTY, PAM_ESTABLISH_CRED, PAM_DELETE_CRED = 3, 0x0002, 0x0004


class Session:
    """One person's sign-in from start to finish, for Huginn's sign-in service (huginn_signind.py, as root):

        s = Session("huginn-signin", "astrid")
        ok, why = s.authenticate(password)      # their password and their account's own rules
        ok, why = s.open({"XDG_SEAT": "seat0", ...}, tty="/dev/tty1")   # the session (logind hears of it here)
        s.env()                                 # what PAM wants in the session's environment
        s.close()                               # when the session is over

    Not for threads: one Session in one process, used and closed by it."""

    def __init__(self, service: str, user: str):
        self.user, self.said, self._secret, self._open, self._cred = user, [], b"", False, False
        pam, libc = _libs()
        pam.pam_set_item.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
        pam.pam_putenv.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        pam.pam_open_session.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_close_session.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_getenvlist.argtypes = [ctypes.c_void_p]
        pam.pam_getenvlist.restype = ctypes.POINTER(ctypes.c_void_p)
        libc.free.argtypes = [ctypes.c_void_p]

        def conv(n, messages, responses, _data):
            replies = libc.calloc(n, ctypes.sizeof(PamResponse))   # PAM frees these itself
            if not replies:
                return 5
            out = ctypes.cast(replies, ctypes.POINTER(PamResponse))
            for i in range(n):
                m = messages[i].contents
                if m.msg_style in (PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON):
                    out[i].resp = libc.strdup(self._secret)
                elif m.msg and m.msg_style in (PAM_ERROR_MSG, PAM_TEXT_INFO):
                    self.said.append(m.msg.decode("utf-8", "replace"))
            responses[0] = out
            return PAM_SUCCESS

        self._cb = CONV(conv)                                      # kept: PAM calls it for as long as the handle lives
        self._talk = PamConv(self._cb, None)
        self._h = ctypes.c_void_p()
        self._rc = pam.pam_start(service.encode(), user.encode(), ctypes.byref(self._talk), ctypes.byref(self._h))
        self.started = self._rc == PAM_SUCCESS

    def _why(self, rc: int) -> str:
        return SAYS.get(rc, (self.said[-1] if self.said else "") or "That didn't work.")

    def authenticate(self, password: str) -> tuple:
        """Their password (or none, for a service that asks for none), then whether the account may sign in now."""
        if not self.started:
            return False, "The password can't be checked right now."
        pam, _libc = _libs()
        self._secret = password.encode("utf-8")
        try:
            rc = pam.pam_authenticate(self._h, 0)
            if rc == PAM_SUCCESS:
                rc = pam.pam_acct_mgmt(self._h, 0)
        finally:
            self._secret = b""
        self._rc = rc
        return (True, "") if rc == PAM_SUCCESS else (False, self._why(rc))

    def open(self, env: dict, tty: str = "") -> tuple:
        """Opens the session: credentials, then every `session` module (pam_systemd tells logind, from `env`)."""
        pam, _libc = _libs()
        if tty:
            pam.pam_set_item(self._h, PAM_TTY, tty.encode())
        for k, v in env.items():
            pam.pam_putenv(self._h, f"{k}={v}".encode())
        rc = pam.pam_setcred(self._h, PAM_ESTABLISH_CRED)
        self._cred = rc == PAM_SUCCESS
        if rc == PAM_SUCCESS:
            rc = pam.pam_open_session(self._h, 0)
            self._open = rc == PAM_SUCCESS
        self._rc = rc
        return (True, "") if rc == PAM_SUCCESS else (False, self._why(rc))

    def env(self) -> dict:
        """PAM's environment for the session (XDG_RUNTIME_DIR and XDG_SESSION_ID from logind, the locale, …)."""
        pam, libc = _libs()
        out, lst = {}, pam.pam_getenvlist(self._h)
        i = 0
        while lst and lst[i]:
            k, _, v = ctypes.cast(lst[i], ctypes.c_char_p).value.decode("utf-8", "replace").partition("=")
            out[k] = v
            libc.free(lst[i])
            i += 1
        if lst:
            libc.free(ctypes.cast(lst, ctypes.c_void_p))
        return out

    def close(self) -> None:
        pam, _libc = _libs()
        if not self.started:
            return
        if self._open:
            self._rc = pam.pam_close_session(self._h, 0)
            self._open = False
        if self._cred:
            pam.pam_setcred(self._h, PAM_DELETE_CRED)
            self._cred = False
        pam.pam_end(self._h, self._rc)
        self.started = False


if __name__ == "__main__":                                         # huginn_pam.py USER  (password on stdin)
    import sys
    ok, why = check(sys.argv[1], sys.stdin.readline().rstrip("\n"), *(sys.argv[2:3]))
    print("yes" if ok else "no: " + why)
    sys.exit(0 if ok else 1)
