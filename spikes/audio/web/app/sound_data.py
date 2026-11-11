"""Sound data (pure Python data, no pyxel import): wavetables, MML, channel plan."""

# ---------------------------------------------------------------- tones (appended after the 4 defaults)
def _pulses(heights, width, sharp):
    """One engine cycle = len(heights) firing pulses; each is a fast rise + decay. 4-bit samples (0..15)."""
    out = []
    for h in heights:
        for i in range(width):
            x = i / width
            v = (1.0 - x) ** sharp  # decay after the firing
            out.append(round(7.5 + 7.5 * h * (2.0 * v - 1.0)))
    return out


TONE_ENGINE_NA = 4  # uneven 4 pulses: buzzy, "lumpy" (half-order harmonics)
TONE_ENGINE_TURBO = 5  # rounder, more even
TONE_SQUEAL = 6  # short-period noise
TONE_HISS = 7  # long-period noise (grass / gravel / contact)

TONES = {  # index: (mode, sample_bits, wavetable, gain)   mode 0 wavetable / 1 short noise / 2 long noise
    TONE_ENGINE_NA: (0, 4, _pulses([1.0, 0.72, 0.92, 0.6], 16, 1.6), 1.0),
    TONE_ENGINE_TURBO: (0, 4, _pulses([1.0, 0.9, 0.97, 0.85], 16, 0.8), 1.0),
    TONE_SQUEAL: (1, 4, [], 1.0),
    TONE_HISS: (2, 4, [], 0.6),
}

# ---------------------------------------------------------------- engine
# One wavetable cycle = one 4-stroke cycle (2 crank revolutions) -> note frequency = rpm / 120.
# Base note O0 C = MIDI 12 = 16.3516 Hz  -> sounds right at ENGINE_REF_RPM.
ENGINE_BASE_HZ = 16.3516
ENGINE_REF_RPM = ENGINE_BASE_HZ * 120.0  # 1962.19 rpm
# T600: 1 tick = 60/(600*48) s = 2.083 ms; L24 = 8 ticks = 1/60 s. @GLI1{*,*}: slide from the previous note's pitch.
ENGINE_LOOP_MML = "T600 Q100 @{tone} V127 @GLI1{{*,*}} O0 L24 C"
ENGINE_LOOP_MML_NOGLIDE = "T600 Q100 @{tone} V127 O0 L24 C"

ENGINES = [  # id: tone, idle, max rpm, gain off/on throttle
    dict(name="NA16", tone=TONE_ENGINE_NA, idle=900.0, max=7600.0, g_off=0.10, g_on=0.22),
    dict(name="TURBO", tone=TONE_ENGINE_TURBO, idle=850.0, max=7000.0, g_off=0.10, g_on=0.22),
]

# ---------------------------------------------------------------- tyres
# Short-period noise: LFSR period 93 clocks. K/Y shift the clock up so the buzz lands around 1.3 kHz.
SQUEAL_LOOP_MML = "T600 Q100 @6 V127 O9 L24 Y3600 B"
SQUEAL_GAIN_MAX = 0.30  # high-clock noise loses most of its energy above 11 kHz, so it needs more gain
HISS_LOOP_MML = "T600 Q100 @7 V127 O7 L24 C"  # off-road roll noise
HISS_GAIN_MAX = 0.12  # long-period noise at a low clock keeps its energy, so it needs far less gain than the squeal

# ---------------------------------------------------------------- one-shot effects (ch2)
SFX = {
    # noise thud with decay, then a low triangle "bump"
    "contact": "T120 Q100 @7 V127 @ENV1{127,8,40,16,0} O5 L16 C @0 @ENV2{120,24,0} O1 L8 G",
    # short mechanical click + lower clunk
    "shift": "T120 Q100 @2 V100 @ENV1{127,4,0} O4 L32 G @1 V80 @ENV2{100,8,0} O2 L16 C",
    # 3-2-1 beep (A4 = 440 Hz, 0.20 s) and GO (A5 = 880 Hz, 0.60 s)
    "count_beep": "T150 Q100 @1 V100 @ENV1{127,20,100,4,0} O4 L8 A",
    "count_go": "T150 Q100 @1 V110 @ENV1{127,60,100,12,0} O5 L8 A&8&8",
}
# looped while the car is on a curb: low square "brrr" (about 28 Hz burst rate)
CURB_LOOP_MML = "T600 Q60 @1 V90 O1 L32 [C R]8"

# ---------------------------------------------------------------- BGM (placeholders generated once with
# pyxel.gen_bgm and frozen here as text; see exp/t05_bgm.py). Each tune = list of parts (melody, bass, ...).
BGM = {}  # filled by bgm_data.py (generated)

# ---------------------------------------------------------------- channel plans
# 4-channel plan (as in the pitch document)
PLAN_4CH = dict(
    race=dict(engine=0, tyre=1, sfx=2, other=3, bgm=[]),
    replay=dict(engine=0, tyre=None, sfx=None, other=3, bgm=[1, 2]),
    menu=dict(engine=None, tyre=None, sfx=3, other=None, bgm=[0, 1, 2]),
)
# 8-channel plan (pyxel.channels can be extended; verified): nothing has to be dropped during replay
PLAN_8CH = dict(engine=0, tyre=1, sfx=2, other=3, bgm=[4, 5, 6, 7])
GAINS_8CH = dict(engine=0.22, tyre=0.30, sfx=0.20, other=0.14, bgm=0.07)  # see the report for the measured peaks
