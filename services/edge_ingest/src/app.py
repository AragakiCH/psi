import logging
from fastapi import FastAPI, WebSocket
from collections import deque
from shared.psi_sdk.signal.fft import compute_spectrum, Spectrum
from .ctrlx.ws_endpoint import websocket_endpoint
from .ctrlx.opc_client import PLCReader
from .ctrlx.buffer import data_buffer
from shared.psi_sdk.config import Settings
from fastapi import HTTPException

log = logging.getLogger("edge_ingest.ctrlx")


app = FastAPI(title="psi-edge-ctrlx-ws", version="0.1.0")
settings = Settings()

WINDOW_SIZE = 256
SAMPLE_FS = 1.0 / settings.ctrlx_opcua_period_s

fft_buffer = deque(maxlen=WINDOW_SIZE)
last_spectrum: Spectrum | None = None
seq = 0

def on_plc_sample(sample: dict) -> None:
    global last_spectrum, spectrum_seq

    real = sample.get("REAL", {})
    value = real.get("VIB_aRMS")
    if value is None:
        return

    fft_buffer.append(float(value))
    log.info("FFT buffer len = %d, VIB_aRMS = %s", len(fft_buffer), value)

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
    return {"status": "ok", "buffer_len": len(data_buffer)}


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
        "seq": seq,
    }


@app.websocket("/ws/ctrlx")
async def ws_ctrlx(websocket: WebSocket):
    await websocket_endpoint(websocket)
