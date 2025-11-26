# shared/psi_sdk/signal/waveform.py
import numpy as np
from dataclasses import dataclass
from scipy import integrate, signal

@dataclass
class WaveformResult:
    time_s: np.ndarray
    accel: np.ndarray
    velocity: np.ndarray | None
    displacement: np.ndarray | None
    fs: float
    cutoff_hz: float

def compute_waveforms(
    signal_data,
    sampling_rate: float,
    compute_velocity: bool = True,
    compute_displacement: bool = True,
    cutoff_hz: float = 2.0,
) -> WaveformResult:
    """
    Calcula forma de onda en el tiempo para aceleración, y opcionalmente
    velocidad y desplazamiento (doble integración con filtros pasa alto).
    """
    accel = np.asarray(signal_data, dtype=float)
    n = len(accel)
    if n == 0:
        raise ValueError("signal_data está vacío")

    dt = 1.0 / sampling_rate
    time_s = np.linspace(0.0, (n - 1) * dt, n)

    vel = None
    disp = None

    if not (compute_velocity or compute_displacement):
        return WaveformResult(time_s=time_s, accel=accel,
                              velocity=None, displacement=None,
                              fs=sampling_rate, cutoff_hz=cutoff_hz)

    nyq = 0.5 * sampling_rate
    if cutoff_hz <= 0 or cutoff_hz >= nyq:
        raise ValueError(
            f"cutoff_hz inválido para fs={sampling_rate} Hz. "
            f"Debe estar entre 0 y {nyq} Hz. Got {cutoff_hz}."
        )

    # Filtro HP a aceleración
    sos_hp = signal.butter(4, cutoff_hz, 'highpass', fs=sampling_rate, output='sos')
    accel_f = signal.sosfiltfilt(sos_hp, accel)

    # Integrar → velocidad
    vel = integrate.cumulative_trapezoid(accel_f, dx=dt, initial=0.0)
    sos_vel = signal.butter(4, cutoff_hz, 'highpass', fs=sampling_rate, output='sos')
    vel_f = signal.sosfiltfilt(sos_vel, vel)

    if not compute_displacement:
        return WaveformResult(
            time_s=time_s,
            accel=accel,
            velocity=vel_f,
            displacement=None,
            fs=sampling_rate,
            cutoff_hz=cutoff_hz,
        )

    # Integrar → desplazamiento
    disp = integrate.cumulative_trapezoid(vel_f, dx=dt, initial=0.0)
    sos_disp = signal.butter(4, cutoff_hz, 'highpass', fs=sampling_rate, output='sos')
    disp_f = signal.sosfiltfilt(sos_disp, disp)

    return WaveformResult(
        time_s=time_s,
        accel=accel,
        velocity=vel_f,
        displacement=disp_f,
        fs=sampling_rate,
        cutoff_hz=cutoff_hz,
    )
