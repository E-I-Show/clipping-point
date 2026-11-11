"""Pyxel-side audio adapter. The only audio code that imports pyxel.

Facts this relies on (verified in the spike):
  * Channel.detune / Channel.gain are read only when a NOTE STARTS. So continuous sounds are
    1-note loops whose note lasts 1/60 s; a write shows up at the next note start.
  * Channel.detune must be an int (float raises TypeError).
  * Tone.gain / Tone.wavetable edits are polled at 60 Hz even inside a sounding note.
  * pyxel.channels / pyxel.tones are lists that can be extended.
"""
import pyxel

import audio_iface as ai
import sound_data as sd
from bgm_data import BGM

BGM_SOUND_BASE = {"menu": 0, "replay": 4, "result": 8}  # 4 bank slots per tune
BGM_MUSIC = {"menu": 0, "replay": 1, "result": 2}


class PyxelAudio:
    def __init__(self, num_channels: int = 8):
        self.n = num_channels
        self.scene = None
        self.picker = ai.NearestPicker()
        self.engine_id = [None, None]  # timbre currently looping on (engine, other)
        self.tyre_mode = None  # None / "squeal" / "hiss"
        self.curb_on = False
        self.errors: list[str] = []
        self._setup()

    # ------------------------------------------------------------ setup (once, after pyxel.init)
    def _setup(self):
        while len(pyxel.channels) < self.n:
            pyxel.channels.append(pyxel.Channel())
        while len(pyxel.tones) < 8:
            pyxel.tones.append(pyxel.Tone())
        for idx, (mode, bits, wt, gain) in sd.TONES.items():
            t = pyxel.tones[idx]
            t.mode, t.sample_bits, t.gain = mode, bits, gain
            t.wavetable[:] = wt
        plan = sd.PLAN_8CH
        self.ch_engine = pyxel.channels[plan["engine"]]
        self.ch_tyre = pyxel.channels[plan["tyre"]]
        self.ch_sfx = pyxel.channels[plan["sfx"]]
        self.ch_other = pyxel.channels[plan["other"]]
        self.bgm_ch = plan["bgm"]
        self.ch_sfx.gain = sd.GAINS_8CH["sfx"]
        for i in self.bgm_ch:
            pyxel.channels[i].gain = sd.GAINS_8CH["bgm"]
        # pre-parse every MML once (a typo raises here, at load time, not in the middle of a race)
        self.snd_engine = {}
        for eid, e in enumerate(sd.ENGINES):
            self.snd_engine[eid] = self._mml(sd.ENGINE_LOOP_MML.format(tone=e["tone"]))
        self.snd_squeal = self._mml(sd.SQUEAL_LOOP_MML)
        self.snd_hiss = self._mml(sd.HISS_LOOP_MML)
        self.snd_curb = self._mml(sd.CURB_LOOP_MML)
        self.snd_sfx = {k: self._mml(v) for k, v in sd.SFX.items()}
        # BGM lives in the sound bank because playm() takes bank indices and starts all parts under one lock.
        # Music seq index == channel index, so pad the front with empty lists (empty = channel left untouched).
        for name, parts in BGM.items():
            base = BGM_SOUND_BASE[name]
            seqs = [[] for _ in range(self.bgm_ch[0])]
            for k, part in enumerate(parts):
                pyxel.sounds[base + k].mml(part)
                seqs.append([base + k] if pyxel.sounds[base + k].total_sec() else [])
            if name == "replay":  # replay: melody + bass only
                seqs = seqs[: self.bgm_ch[0] + 2]
            pyxel.musics[BGM_MUSIC[name]].set(*seqs)

    @staticmethod
    def _mml(code: str):
        s = pyxel.Sound()
        s.mml(code)
        return s

    # ------------------------------------------------------------ scene / BGM
    def _enter_scene(self, scene: ai.Scene):
        pyxel.stop()
        self.engine_id = [None, None]
        self.tyre_mode = None
        self.curb_on = False
        name = {ai.Scene.MENU: "menu", ai.Scene.REPLAY: "replay", ai.Scene.RESULT: "result"}.get(scene)
        if name:
            pyxel.playm(BGM_MUSIC[name], loop=True)
        self.scene = scene

    # ------------------------------------------------------------ per tick (call from update, 60 Hz)
    def update(self, f: ai.AudioFrame):
        if f.scene != self.scene:
            self._enter_scene(f.scene)
        live = f.scene in (ai.Scene.RACE, ai.Scene.REPLAY) and not f.paused
        self._engine(0, self.ch_engine, f.player if live else None, sd.GAINS_8CH["engine"])
        other = None
        if live and f.others:
            i = self.picker.pick([c.dist for c in f.others])
            other = f.others[i]
        self._engine(1, self.ch_other, other, sd.GAINS_8CH["other"])
        self._tyre(f.player if live else None)
        self._curb(bool(live and f.player and f.player.on_curb))
        for ev, strength in f.events:
            self._event(ev, strength)

    def _engine(self, slot: int, ch, car, g_scale: float):
        if car is None:
            if self.engine_id[slot] is not None:
                ch.stop()
                self.engine_id[slot] = None
            return
        e = sd.ENGINES[car.engine]
        if self.engine_id[slot] != car.engine or ch.play_pos() is None:
            ch.play(self.snd_engine[car.engine], loop=True)
            self.engine_id[slot] = car.engine
        ch.detune = ai.rpm_to_detune(car.rpm, sd.ENGINE_REF_RPM)
        g = ai.engine_gain(car.throttle, car.rpm, e["idle"], e["max"], e["g_off"], e["g_on"]) / e["g_on"]
        ch.gain = g_scale * g * (ai.distance_gain(car.dist) if slot == 1 else 1.0)

    def _tyre(self, car):
        mode = None
        if car is not None:
            if car.off_road and car.speed > 2.0:
                mode = "hiss"
            elif car.slip > 0.15:
                mode = "squeal"
        if mode != self.tyre_mode:
            if mode is None:
                self.ch_tyre.stop()
            else:
                self.ch_tyre.play(self.snd_squeal if mode == "squeal" else self.snd_hiss, loop=True)
            self.tyre_mode = mode
        if mode == "squeal":
            self.ch_tyre.gain = ai.squeal_gain(car.slip, sd.SQUEAL_GAIN_MAX)
            self.ch_tyre.detune = int(-300 + 500 * car.slip)  # pitch rises a little with slip
        elif mode == "hiss":
            self.ch_tyre.gain = sd.HISS_GAIN_MAX * min(car.speed / 30.0, 1.0)
            self.ch_tyre.detune = 0

    def _curb(self, on: bool):
        if on and not self.curb_on:
            self.ch_sfx.play(self.snd_curb, loop=True)
        elif not on and self.curb_on:
            self.ch_sfx.stop()
        self.curb_on = on

    def _event(self, ev: ai.Ev, strength: float):
        name = {ai.Ev.CONTACT: "contact", ai.Ev.SHIFT: "shift",
                ai.Ev.COUNT_BEEP: "count_beep", ai.Ev.COUNT_GO: "count_go"}[ev]
        self.ch_sfx.gain = sd.GAINS_8CH["sfx"] * (0.4 + 0.6 * min(max(strength, 0.0), 1.0))
        # resume=True: when the one-shot ends, the curb loop (if any) comes back by itself
        self.ch_sfx.play(self.snd_sfx[name], resume=True)
