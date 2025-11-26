import logging
from fastapi import FastAPI, WebSocket
from collections import deque
from shared.psi_sdk.signal import (
    Spectrum,
    EnvelopeResult,
    compute_spectrum,
    calculate_envelope,
    WaveformResult,
    compute_waveforms,
)
from .ctrlx.ws_endpoint import websocket_endpoint
from .ctrlx.opc_client import PLCReader
from .ctrlx.buffer import data_buffer
import numpy as np
from shared.psi_sdk.config import Settings
from fastapi import HTTPException


log = logging.getLogger("edge_ingest.ctrlx")


app = FastAPI(title="psi-edge-ctrlx-ws", version="0.1.0")
settings = Settings()

WINDOW_SIZE = 256
SAMPLE_FS = 1.0 / settings.ctrlx_opcua_period_s
ENV_HP = 0.5   # Hz  (< fs/2 = 5)
ENV_LP = 3.0   # Hz  (< fs/2 y > ENV_HP)

# ---- FFT ----
fft_buffer = deque(maxlen=WINDOW_SIZE)
last_spectrum: Spectrum | None = None
spectrum_seq = 0

# ---- Envolvente ----
env_buffer = deque(maxlen=WINDOW_SIZE)
last_envelope: EnvelopeResult | None = None
envelope_seq = 0

wave_buffer = deque(maxlen=WINDOW_SIZE)
last_waveform: WaveformResult | None = None
wave_seq = 0

def on_plc_sample(sample: dict) -> None:
    global last_spectrum, spectrum_seq, last_envelope, envelope_seq, last_waveform, wave_seq

    real = sample.get("REAL", {})

    # --- FFT: usa VIB_aRMS (ajusta si estás usando otro) ---
    fft_val = real.get("VIB_aRMS")
    if fft_val is not None:
        fft_buffer.append(float(fft_val))

        if len(fft_buffer) == WINDOW_SIZE:
            spec = compute_spectrum(
                list(fft_buffer),
                sampling_rate=SAMPLE_FS,
                use_log_scale=False,
                scale_to_peak=True,
            )
            last_spectrum = spec
            spectrum_seq += 1
            log.info("Nuevo espectro calculado, seq=%s", spectrum_seq)

    # --- Envolvente: usa VIB_aPeak (o el canal que quieras) ---
    env_val = real.get("VIB_aPeak")   # <-- cambia al tag correcto si usas otro
    if env_val is not None:
        env_buffer.append(float(env_val))

        if len(env_buffer) >= WINDOW_SIZE:
            window = np.array(env_buffer, dtype=float)

            try:
                env = calculate_envelope(
                    window,
                    sampling_rate=SAMPLE_FS,
                    high_pass_cutoff_hz=ENV_HP,
                    low_pass_cutoff_hz=ENV_LP,
                )
                last_envelope = env
                envelope_seq += 1
                env_buffer.clear()
                log.info(
                    "envelope updated seq=%s, len=%s",
                    envelope_seq,
                    len(env.envelope),
                )
            except Exception as e:
                log.exception("on_sample envelope error: %s", e)
    
    wave_val = real.get("VIB_aPeak")
    if wave_val is not None:
        wave_buffer.append(float(wave_val))

        if len(wave_buffer) == WINDOW_SIZE:
            try:
                wf = compute_waveforms(
                    wave_buffer,
                    sampling_rate=SAMPLE_FS,
                    compute_velocity=True,
                    compute_displacement=True,
                    cutoff_hz=ENV_HP,  # o el que definas
                )
                last_waveform = wf
                wave_seq += 1
                log.info("waveform updated seq=%s", wave_seq)
            except Exception as e:
                log.exception("on_sample waveform error: %s", e)


@app.on_event("startup")

def startup() -> None:
    reader = PLCReader(
        url=settings.ctrlx_opcua_url,
        user=settings.ctrlx_opcua_user,
        password=settings.ctrlx_opcua_password,
        buffer=data_buffer,
        buffer_size=1000,
        period_s=settings.ctrlx_opcua_period_s,
        on_sample=on_plc_sample,
    )
    reader.start()
    app.state.plc_reader = reader
    log.info("PLCReader arrancado contra %s", settings.ctrlx_opcua_url)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "buffer_len": len(data_buffer),
        "spectrum_ready": last_spectrum is not None,
        "spectrum_seq": spectrum_seq,
        "envelope_ready": last_envelope is not None,
        "envelope_seq": envelope_seq,
        "waveform_ready": last_waveform is not None,
        "wave_seq": wave_seq,
    }


@app.get("/spectrum")
def get_spectrum():
    if last_spectrum is None:
        raise HTTPException(status_code=404, detail="No spectrum computed yet")

    spec = last_spectrum
    return {
        "fs": spec.fs,
        "scale": spec.scale,
        "scale_to_peak": spec.scale_to_peak,
        "freqs_hz": spec.freqs_hz.tolist(),
        "magnitudes": spec.magnitudes.tolist(),
        "seq": spectrum_seq,
    }

@app.get("/envelope")
def get_envelope():
    if last_envelope is None:
        raise HTTPException(status_code=404, detail="No envelope computed yet")

    env = last_envelope
    return {
        "fs": env.fs,
        "high_pass_hz": env.high_pass_hz,
        "low_pass_hz": env.low_pass_hz,
        "envelope": env.envelope.tolist(),
        "seq": envelope_seq,
    }


@app.get("/waveform")
def get_waveform():
    if last_waveform is None:
        raise HTTPException(status_code=404, detail="No waveform computed yet")

    wf = last_waveform
    return {
        "fs": wf.fs,
        "cutoff_hz": wf.cutoff_hz,
        "seq": wave_seq,
        "time_s": wf.time_s.tolist(),
        "accel": wf.accel.tolist(),
        "velocity": wf.velocity.tolist() if wf.velocity is not None else None,
        "displacement": wf.displacement.tolist() if wf.displacement is not None else None,
    }


@app.websocket("/ws/ctrlx")
async def ws_ctrlx(websocket: WebSocket):
    await websocket_endpoint(websocket)
