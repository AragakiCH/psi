# shared/psi_sdk/signal/fft.py

import numpy as np
from dataclasses import dataclass
from typing import Literal

ScaleMode = Literal["linear", "db"]

@dataclass
class Spectrum:
    freqs_hz: np.ndarray
    magnitudes: np.ndarray
    scale: ScaleMode
    scale_to_peak: bool
    fs: float

def compute_spectrum(
    signal_data,
    sampling_rate: float,
    use_log_scale: bool = False,
    scale_to_peak: bool = False,
) -> Spectrum:
    signal_array = np.array(signal_data, dtype=float)
    N = len(signal_array)
    if N == 0:
        raise ValueError("Signal data is empty.")

    # FFT
    fft_result_complex = np.fft.fft(signal_array)
    frequencies = np.fft.fftfreq(N, d=1.0 / sampling_rate)

    fft_magnitude = np.abs(fft_result_complex) * 2.0 / N
    fft_magnitude[0] /= 2.0  # DC

    # solo lado positivo
    pos_idx = np.where(frequencies >= 0)[0]
    freqs_hz = frequencies[pos_idx]
    magnitudes = fft_magnitude[pos_idx]

    if scale_to_peak:
        magnitudes = magnitudes * np.sqrt(2)
        magnitudes[0] /= np.sqrt(2)

    scale: ScaleMode = "linear"

    if use_log_scale:
        epsilon = 1e-12
        magnitudes = 20 * np.log10(np.maximum(magnitudes, epsilon))
        scale = "db"

    return Spectrum(
        freqs_hz=freqs_hz,
        magnitudes=magnitudes,
        scale=scale,
        scale_to_peak=scale_to_peak,
        fs=sampling_rate,
    )
