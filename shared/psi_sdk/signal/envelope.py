import numpy as np
from dataclasses import dataclass
from typing import Optional
from scipy import signal  # filtros IIR

@dataclass
class EnvelopeResult:
    envelope: np.ndarray
    fs: float
    high_pass_hz: float
    low_pass_hz: float


def calculate_envelope(
    signal_data,
    sampling_rate: float,
    high_pass_cutoff_hz: float = 1000.0,
    low_pass_cutoff_hz: float = 100.0,
) -> EnvelopeResult:
    """
    Calcula la envolvente de una señal de vibración por:
      1) Filtro paso alto
      2) Rectificación (valor absoluto)
      3) Filtro paso bajo
    """

    signal_array = np.array(signal_data, dtype=float)
    N = len(signal_array)
    if N == 0:
        raise ValueError("Signal data is empty.")

    nyq = 0.5 * sampling_rate
    if high_pass_cutoff_hz <= 0 or low_pass_cutoff_hz <= 0:
        raise ValueError("Cutoff frequencies must be > 0 Hz.")
    if high_pass_cutoff_hz >= nyq or low_pass_cutoff_hz >= nyq:
        raise ValueError(
            f"Invalid cutoff frequencies for fs={sampling_rate} Hz. "
            f"Must satisfy 0 < hp, lp < fs/2={nyq} Hz. "
            f"Got hp={high_pass_cutoff_hz}, lp={low_pass_cutoff_hz}."
        )
    if high_pass_cutoff_hz >= low_pass_cutoff_hz:
        raise ValueError(
            f"high_pass_cutoff_hz ({high_pass_cutoff_hz}) must be < "
            f"low_pass_cutoff_hz ({low_pass_cutoff_hz})."
        )

    # 1. Paso alto
    sos_hp = signal.butter(
        4, high_pass_cutoff_hz, "highpass", fs=sampling_rate, output="sos"
    )
    filtered_high = signal.sosfiltfilt(sos_hp, signal_array)

    # 2. Rectificación
    rectified = np.abs(filtered_high)

    # 3. Paso bajo
    sos_lp = signal.butter(
        4, low_pass_cutoff_hz, "lowpass", fs=sampling_rate, output="sos"
    )
    envelope_signal = signal.sosfiltfilt(sos_lp, rectified)

    return EnvelopeResult(
        envelope=envelope_signal,
        fs=sampling_rate,
        high_pass_hz=high_pass_cutoff_hz,
        low_pass_hz=low_pass_cutoff_hz,
    )
