# services/edge_ingest/src/ctrlx/metrics_processor.py
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Optional

import numpy as np

from shared.psi_sdk.signal import (
    Spectrum,
    EnvelopeResult,
    WaveformResult,
    compute_spectrum,
    calculate_envelope,
    compute_waveforms,
)

@dataclass
class MetricsConfig:
    window_size: int = 256
    fs: float = 10.0

    # Tags (se leen del dict REAL del PLC)
    tag_fft: str = "VIB_aRMS"
    tag_env: str = "VIB_aPeak"
    tag_wave: str = "VIB_aPeak"

    # Envelope params
    env_hp: float = 0.5
    env_lp: float = 3.0

    # Waveform params
    wave_cutoff_hz: float = 0.5
    wave_compute_velocity: bool = True
    wave_compute_displacement: bool = True

    # Modo de cálculo
    fft_sliding: bool = True
    env_sliding: bool = False   # si False => por bloques (clear)
    wave_sliding: bool = True


class MetricsProcessor:
    def __init__(self, cfg: MetricsConfig):
        self.cfg = cfg

        # buffers
        self.fft_buffer = deque(maxlen=cfg.window_size)
        self.env_buffer = deque(maxlen=cfg.window_size)
        self.wave_buffer = deque(maxlen=cfg.window_size)

        # últimos resultados
        self.last_spectrum: Optional[Spectrum] = None
        self.last_envelope: Optional[EnvelopeResult] = None
        self.last_waveform: Optional[WaveformResult] = None

        # seq
        self.spectrum_seq = 0
        self.envelope_seq = 0
        self.wave_seq = 0

    def update(self, sample: dict) -> None:
        real = sample.get("REAL", {}) or {}

        self._update_fft(real)
        self._update_envelope(real)
        self._update_waveform(real)

    def _update_fft(self, real: dict) -> None:
        v = real.get(self.cfg.tag_fft)
        if v is None:
            return

        self.fft_buffer.append(float(v))

        if len(self.fft_buffer) < self.cfg.window_size:
            return

        spec = compute_spectrum(
            list(self.fft_buffer),
            sampling_rate=self.cfg.fs,
            use_log_scale=False,
            scale_to_peak=True,
        )
        self.last_spectrum = spec
        self.spectrum_seq += 1

        if not self.cfg.fft_sliding:
            self.fft_buffer.clear()

    def _update_envelope(self, real: dict) -> None:
        v = real.get(self.cfg.tag_env)
        if v is None:
            return

        self.env_buffer.append(float(v))

        if len(self.env_buffer) < self.cfg.window_size:
            return

        window = np.asarray(self.env_buffer, dtype=float)

        env = calculate_envelope(
            window,
            sampling_rate=self.cfg.fs,
            high_pass_cutoff_hz=self.cfg.env_hp,
            low_pass_cutoff_hz=self.cfg.env_lp,
        )
        self.last_envelope = env
        self.envelope_seq += 1

        if not self.cfg.env_sliding:
            self.env_buffer.clear()

    def _update_waveform(self, real: dict) -> None:
        v = real.get(self.cfg.tag_wave)
        if v is None:
            return

        self.wave_buffer.append(float(v))

        if len(self.wave_buffer) < self.cfg.window_size:
            return

        wf = compute_waveforms(
            self.wave_buffer,
            sampling_rate=self.cfg.fs,
            compute_velocity=self.cfg.wave_compute_velocity,
            compute_displacement=self.cfg.wave_compute_displacement,
            cutoff_hz=self.cfg.wave_cutoff_hz,
        )
        self.last_waveform = wf
        self.wave_seq += 1

        if not self.cfg.wave_sliding:
            self.wave_buffer.clear()
