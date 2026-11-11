"""Browser bridge for a Pyxel Web game (Pyxel 3.0.1 / Pyodide 314.0.7). Adapter layer only.

Everything here was exercised in headless Chromium by apps/bridge_demo (see REPORT.md).
Importing this module on native CPython is safe: the web-only parts are behind IS_WEB and the
native fallbacks keep the same call shapes so the game code does not branch.

    store = Storage("clippingpoint.v1")
    store.put("replay.03", data)          # raises StorageFull when the browser quota is hit
    data = store.get("replay.03")         # bytes or None
    save_file("lap.cpr", data)            # browser download / native: writes the file
    request_open_file(".cpr")             # opens the file dialog; call on the frame a button was pressed
    for name, data in poll_files(): ...   # call every update(): picked files + files dropped on the screen
    lt, rt = read_triggers(0)             # analog trigger values 0..1 (Pyxel only reports them on/off on the web)
"""

import base64
import os
import sys

IS_WEB = sys.platform == "emscripten"

if IS_WEB:
    import js
    from pyodide.ffi import JsException, create_once_callable, create_proxy, to_js


class StorageFull(Exception):
    """The browser refused the write (QuotaExceededError). Nothing was changed."""


class Storage:
    """Namespaced bytes store. Web: localStorage (values are base64 text). Native: a directory."""

    def __init__(self, namespace, native_dir=".storage"):
        self._prefix = namespace + "/"
        self._dir = native_dir

    # ---- web
    def _ls(self):
        return js.localStorage

    def keys(self):
        if IS_WEB:
            ls = self._ls()
            names = [str(ls.key(i)) for i in range(int(ls.length))]
            return sorted(n[len(self._prefix) :] for n in names if n.startswith(self._prefix))
        if not os.path.isdir(self._dir):
            return []
        return sorted(os.listdir(self._dir))

    def get(self, key):
        if IS_WEB:
            v = self._ls().getItem(self._prefix + key)
            # A missing key is JS null. Pyodide 314 maps null to pyodide.ffi.jsnull, NOT None.
            if not isinstance(v, str):
                return None
            return base64.b64decode(v)
        path = os.path.join(self._dir, key)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def put(self, key, data):
        if IS_WEB:
            text = base64.b64encode(data).decode("ascii")
            try:
                self._ls().setItem(self._prefix + key, text)
            except JsException as e:
                if str(getattr(e, "name", "")) == "QuotaExceededError":
                    raise StorageFull(key) from None
                raise
            return
        os.makedirs(self._dir, exist_ok=True)
        with open(os.path.join(self._dir, key), "wb") as f:
            f.write(data)

    def delete(self, key):
        if IS_WEB:
            self._ls().removeItem(self._prefix + key)
            return
        path = os.path.join(self._dir, key)
        if os.path.exists(path):
            os.remove(path)

    def used_chars(self):
        """Characters this namespace occupies (keys + values). The browser quota counts characters."""
        if not IS_WEB:
            return sum(os.path.getsize(os.path.join(self._dir, k)) for k in self.keys())
        ls = self._ls()
        total = 0
        for i in range(int(ls.length)):
            name = str(ls.key(i))
            if name.startswith(self._prefix):
                total += len(name) + len(ls.getItem(name))
        return total


def save_file(filename, data):
    """Hand `data` to the user as a file named `filename`."""
    if not IS_WEB:
        with open(filename, "wb") as f:
            f.write(data)
        return
    parts = js.Array.new()
    parts.push(to_js(data))  # bytes -> Uint8Array
    opts = js.Object.new()
    opts.type = "application/octet-stream"
    url = js.URL.createObjectURL(js.Blob.new(parts, opts))
    a = js.document.createElement("a")
    a.href = url
    a.download = filename
    a.style.display = "none"
    js.document.body.appendChild(a)
    a.click()
    js.document.body.removeChild(a)
    js.setTimeout(create_once_callable(lambda: js.URL.revokeObjectURL(url)), 2000)


_inbox = []  # (name, bytes) delivered by browser callbacks between frames
_errors = []
_proxies = []  # keep callback proxies alive for the life of the page
_input = None


def request_open_file(accept=".cpr"):
    """Open the browser's file dialog. The result arrives later through poll_files().

    Call it on the frame the player pressed the key/button: browsers only show the dialog
    shortly after a user gesture. Native: no dialog (drag and drop only).
    """
    global _input
    if not IS_WEB:
        return False
    if _input is None:
        _input = js.document.createElement("input")
        _input.type = "file"
        _input.style.display = "none"
        js.document.body.appendChild(_input)

        def on_change(_event):
            files = _input.files
            if int(files.length) == 0:
                return
            f = files.item(0)
            name = str(f.name)

            def on_buffer(buf):
                _inbox.append((name, buf.to_bytes()))

            def on_error(err):
                _errors.append("%s: %s" % (name, err))

            f.arrayBuffer().then(create_once_callable(on_buffer), create_once_callable(on_error))
            _input.value = ""  # picking the same file again must fire "change" again

        p = create_proxy(on_change)
        _proxies.append(p)
        _input.addEventListener("change", p)
    _input.accept = accept
    _input.click()
    return True


def poll_files(pyxel_module):
    """Files that arrived since the last call: [(name, bytes)]. Call once per update()."""
    out = list(_inbox)
    del _inbox[:]
    # Files dropped on the screen. The web runtime writes them to /tmp/<sanitised name> and
    # appends the path to the module attribute pyxel._dropped_files (pyxel.dropped_files stays
    # empty on the web); native Pyxel fills pyxel.dropped_files for one frame.
    paths = list(pyxel_module.dropped_files)
    legacy = getattr(pyxel_module, "_dropped_files", None)
    if legacy:
        paths += list(legacy)
        pyxel_module._dropped_files = []
    for path in paths:
        with open(path, "rb") as f:
            out.append((os.path.basename(path), f.read()))
    return out


def poll_errors():
    out = list(_errors)
    del _errors[:]
    return out


def read_triggers(pad_index=0):
    """Analog trigger values (left, right) in 0..1 from the browser Gamepad API, or None.

    On the web Pyxel/SDL maps the triggers of a "standard" gamepad from buttons 6/7 and only
    reports 0 or 32767 through GAMEPADn_AXIS_TRIGGERLEFT/RIGHT. Native: returns None, use btnv.
    """
    if not IS_WEB:
        return None
    pads = js.navigator.getGamepads()
    if pad_index >= int(pads.length):
        return None
    pad = pads[pad_index]
    if not hasattr(pad, "buttons") or str(pad.mapping) != "standard" or int(pad.buttons.length) < 8:
        return None
    return float(pad.buttons[6].value), float(pad.buttons[7].value)
