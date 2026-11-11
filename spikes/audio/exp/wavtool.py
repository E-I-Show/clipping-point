"""Small analysis helpers (numpy): load WAV / raw s16le mono 22050 Hz, f0 and RMS tracks."""
import wave

import numpy as np

SR = 22050


def load_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, (w.getnchannels(), w.getsampwidth())
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    return data, sr


def load_raw(path):
    return np.fromfile(str(path), dtype="<i2").astype(np.float64), SR


def rms_track(x, sr=SR, win=0.010):
    n = int(sr * win)
    m = len(x) // n
    return np.sqrt((x[: m * n].reshape(m, n) ** 2).mean(axis=1)), win


def f0_autocorr(seg, sr=SR, fmin=20.0, fmax=5000.0):
    """Fundamental estimate by unbiased normalized autocorrelation + parabolic refinement. 0 if silent."""
    seg = seg - seg.mean()
    if np.sqrt((seg**2).mean()) < 20:
        return 0.0
    n = len(seg)
    spec = np.fft.rfft(seg, 2 * n)
    ac = np.fft.irfft(spec * np.conj(spec))[:n]
    ac = ac / (n - np.arange(n))  # unbiased
    ac /= ac[0] + 1e-9
    lo = max(2, int(sr / fmax))
    hi = min(n // 2, int(sr / fmin) + 2)
    if hi <= lo + 2:
        return 0.0
    # skip the initial descent from lag 0 (only when the search starts inside it)
    start = lo
    if ac[lo] > 0.5:
        below = np.nonzero(ac[lo:hi] < 0.3)[0]
        if len(below) == 0:
            return 0.0
        start = lo + int(below[0])
    rng = ac[start:hi]
    if len(rng) < 3:
        return 0.0
    thr = rng.max() * 0.92
    k = None
    for i in range(1, len(rng) - 1):
        if rng[i] >= thr and rng[i] >= rng[i - 1] and rng[i] >= rng[i + 1]:
            k = i + start
            break
    if k is None:
        return 0.0
    a, b, c = ac[k - 1], ac[k], ac[k + 1]
    d = (a - c) / (2 * (a - 2 * b + c) + 1e-12)
    return sr / (k + d)


def f0_track(x, sr=SR, win=0.040, hop=0.010, **kw):
    n, h = int(sr * win), int(sr * hop)
    out = []
    for s in range(0, len(x) - n, h):
        out.append(((s + n / 2) / sr, f0_autocorr(x[s : s + n], sr, **kw)))
    return out


def spectrum_peaks(seg, sr=SR, count=8):
    seg = seg - seg.mean()
    w = np.hanning(len(seg))
    sp = np.abs(np.fft.rfft(seg * w))
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    idx = [i for i in range(1, len(sp) - 1) if sp[i] > sp[i - 1] and sp[i] >= sp[i + 1]]
    idx.sort(key=lambda i: -sp[i])
    top = idx[:count]
    m = sp[top[0]] if top else 1.0
    return [(round(float(freqs[i]), 1), round(float(20 * np.log10(sp[i] / m + 1e-12)), 1)) for i in sorted(top)]


def cents(f, ref):
    return 1200 * np.log2(f / ref) if f > 0 and ref > 0 else float("nan")


def zero_crossings(x, sr=SR, hyst=0.0):
    """Times (s) of positive-going zero crossings, linearly interpolated. hyst = required negative depth before."""
    x = x - x.mean()
    out = []
    armed = False
    for i in range(1, len(x)):
        if x[i - 1] < -hyst:
            armed = True
        if armed and x[i - 1] < 0 <= x[i]:
            out.append((i - 1 + (-x[i - 1]) / (x[i] - x[i - 1] + 1e-12)) / sr)
            armed = False
    return out


def f0_zc(x, sr=SR, hyst_ratio=0.2):
    """Mean frequency over the segment from zero-crossing spacing (clean single-zero-crossing waves only)."""
    if len(x) < 8 or np.abs(x).max() < 20:
        return 0.0
    zc = zero_crossings(x, sr, hyst=np.abs(x - x.mean()).max() * hyst_ratio)
    if len(zc) < 2:
        return 0.0
    return (len(zc) - 1) / (zc[-1] - zc[0])


def f0_zc_track(x, sr=SR, hyst_ratio=0.2):
    """Instantaneous frequency per period: list of (t_mid, f)."""
    zc = zero_crossings(x, sr, hyst=np.abs(x - x.mean()).max() * hyst_ratio)
    return [((a + b) / 2, 1.0 / (b - a)) for a, b in zip(zc, zc[1:]) if b > a]
