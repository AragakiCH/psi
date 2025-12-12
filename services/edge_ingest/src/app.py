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
from .ctrlx.metrics_processor import MetricsProcessor, MetricsConfig



log = logging.getLogger("edge_ingest.ctrlx")


app = FastAPI(title="psi-edge-ctrlx-ws", version="0.1.0")
settings = Settings()

WINDOW_SIZE = 256
SAMPLE_FS = 1.0 / settings.ctrlx_opcua_period_s
ENV_HP = 0.5   # Hz  (< fs/2 = 5)
ENV_LP = 3.0   # Hz  (< fs/2 y > ENV_HP)

processor = MetricsProcessor(
    MetricsConfig(
        window_size=WINDOW_SIZE,
        fs=SAMPLE_FS,
        tag_fft="VIB_aRMS",
        tag_env="VIB_aPeak",
        tag_wave="VIB_aPeak",
        env_hp=ENV_HP,
        env_lp=ENV_LP,
        wave_cutoff_hz=ENV_HP,
        fft_sliding=True,
        env_sliding=False,
        wave_sliding=True,
    )
)

def on_plc_sample(sample: dict) -> None:
    try:
        processor.update(sample)
    except Exception as e:
        log.exception("on_sample processing error: %s", e)


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
        "spectrum_ready": processor.last_spectrum is not None,
        "spectrum_seq": processor.spectrum_seq,
        "envelope_ready": processor.last_envelope is not None,
        "envelope_seq": processor.envelope_seq,
        "waveform_ready": processor.last_waveform is not None,
        "wave_seq": processor.wave_seq,
    }


@app.get("/spectrum")
def get_spectrum():
    if processor.last_spectrum is None:
        raise HTTPException(status_code=404, detail="No spectrum computed yet")
    spec = processor.last_spectrum
    return {
        "fs": spec.fs,
        "scale": spec.scale,
        "scale_to_peak": spec.scale_to_peak,
        "freqs_hz": spec.freqs_hz.tolist(),
        "magnitudes": spec.magnitudes.tolist(),
        "seq": processor.spectrum_seq,
    }

@app.get("/envelope")
def get_envelope():
    if processor.last_envelope is None:
        raise HTTPException(status_code=404, detail="No envelope computed yet")
    env = processor.last_envelope
    return {
        "fs": env.fs,
        "high_pass_hz": env.high_pass_hz,
        "low_pass_hz": env.low_pass_hz,
        "envelope": env.envelope.tolist(),
        "seq": processor.envelope_seq,
    }


@app.get("/waveform")
def get_waveform():
    if processor.last_waveform is None:
        raise HTTPException(status_code=404, detail="No waveform computed yet")
    wf = processor.last_waveform
    return {
        "fs": wf.fs,
        "cutoff_hz": wf.cutoff_hz,
        "seq": processor.wave_seq,
        "time_s": wf.time_s.tolist(),
        "accel": wf.accel.tolist(),
        "velocity": wf.velocity.tolist() if wf.velocity is not None else None,
        "displacement": wf.displacement.tolist() if wf.displacement is not None else None,
    }


@app.websocket("/ws/ctrlx")
async def ws_ctrlx(websocket: WebSocket):
    await websocket_endpoint(websocket)
