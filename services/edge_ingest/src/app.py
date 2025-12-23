# services/edge_ingest/src/app.py
import logging
from fastapi import FastAPI, WebSocket, HTTPException

import numpy as np

from shared.psi_sdk.config import Settings
from .ctrlx.ws_endpoint import websocket_endpoint
from .ctrlx.opc_client import PLCReader
from .ctrlx.buffer import data_buffer
from .ctrlx.metrics_processor import MetricsProcessor, MetricsConfig
from .ctrlx.influx_writer import InfluxWriter, InfluxCfg

log = logging.getLogger("edge_ingest.ctrlx")

app = FastAPI(title="psi-edge-ctrlx-ws", version="0.1.0")
settings = Settings()

WINDOW_SIZE = 256
SAMPLE_FS = 1.0 / settings.ctrlx_opcua_period_s
ENV_HP = 0.5   # Hz
ENV_LP = 3.0   # Hz

ASSET_ID = "BP-101"  # pon aquí el ID de tu equipo

# ========= InfluxDB writers =========
influx_telemetry = InfluxWriter(
    InfluxCfg(
        url=settings.influx_url,
        token=settings.influx_token,
        org=settings.influx_org,
        bucket=settings.influx_bucket_telemetry,
    )
)

influx_features = InfluxWriter(
    InfluxCfg(
        url=settings.influx_url,
        token=settings.influx_token,
        org=settings.influx_org,
        bucket=settings.influx_bucket_features,
    )
)

# ========= Procesador de métricas =========
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

# Para no escribir la misma ventana varias veces
last_written_spec_seq = -1
last_written_env_seq = -1
last_written_wave_seq = -1


def on_plc_sample(sample: dict) -> None:
    """Callback que se ejecuta en cada muestra del PLC."""
    global last_written_spec_seq, last_written_env_seq, last_written_wave_seq

    try:
        # 1) Actualizar cálculos (FFT, envelope, waveform)
        processor.update(sample)

        real = sample.get("REAL", {}) or {}

        # 2) Telemetría cruda -> bucket "telemetry"
        for sig in ["VIB_aRMS", "VIB_aPeak", "VIB_vRMS", "VIB_TempSurface"]:
            val = real.get(sig)
            if val is not None:
                try:
                    influx_telemetry.write_telemetry(ASSET_ID, sig, float(val))
                except Exception as e:
                    log.exception("Error escribiendo telemetría %s: %s", sig, e)

        # 3) Features de FFT -> bucket "features"
        if processor.last_spectrum is not None and processor.spectrum_seq != last_written_spec_seq:
            spec = processor.last_spectrum
            mags = spec.magnitudes
            freqs = spec.freqs_hz

            if len(mags) > 0:
                peak_idx = int(np.argmax(mags))
                peak_freq = float(freqs[peak_idx])
                peak_amp = float(mags[peak_idx])
                overall_rms = float(np.sqrt(np.mean(mags**2)))

                try:
                    influx_features.write_feature(ASSET_ID, "fft_peak_freq_hz", peak_freq)
                    influx_features.write_feature(ASSET_ID, "fft_peak_amp", peak_amp)
                    influx_features.write_feature(ASSET_ID, "fft_overall_rms", overall_rms)
                except Exception as e:
                    log.exception("Error escribiendo features FFT: %s", e)

            last_written_spec_seq = processor.spectrum_seq

        # 4) Features de Envelope -> bucket "features"
        if processor.last_envelope is not None and processor.envelope_seq != last_written_env_seq:
            env_arr = processor.last_envelope.envelope
            if len(env_arr) > 0:
                env_rms = float(np.sqrt(np.mean(env_arr**2)))
                env_peak = float(np.max(np.abs(env_arr)))
                env_crest = float(env_peak / env_rms) if env_rms > 0 else 0.0

                try:
                    influx_features.write_feature(ASSET_ID, "env_rms", env_rms)
                    influx_features.write_feature(ASSET_ID, "env_peak", env_peak)
                    influx_features.write_feature(ASSET_ID, "env_crest_factor", env_crest)
                except Exception as e:
                    log.exception("Error escribiendo features Envelope: %s", e)

            last_written_env_seq = processor.envelope_seq

        # 5) Features de Waveform -> bucket "features"
        if processor.last_waveform is not None and processor.wave_seq != last_written_wave_seq:
            wf = processor.last_waveform
            acc = wf.accel
            vel = wf.velocity
            disp = wf.displacement

            try:
                if len(acc) > 0:
                    acc_rms = float(np.sqrt(np.mean(acc**2)))
                    acc_p2p = float(np.max(acc) - np.min(acc))
                    influx_features.write_feature(ASSET_ID, "wave_acc_rms", acc_rms)
                    influx_features.write_feature(ASSET_ID, "wave_acc_p2p", acc_p2p)

                if vel is not None and len(vel) > 0:
                    vel_rms = float(np.sqrt(np.mean(vel**2)))
                    influx_features.write_feature(ASSET_ID, "wave_vel_rms", vel_rms)

                if disp is not None and len(disp) > 0:
                    disp_p2p = float(np.max(disp) - np.min(disp))
                    influx_features.write_feature(ASSET_ID, "wave_disp_p2p", disp_p2p)
            except Exception as e:
                log.exception("Error escribiendo features Waveform: %s", e)

            last_written_wave_seq = processor.wave_seq

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

# ========= ENDPOINTS DINÁMICOS =========

# FFT
@app.get("/spectrum/select/{tag}")
def set_spectrum_tag(tag: str):
    processor.cfg.tag_fft = tag
    processor.fft_buffer.clear()
    processor.last_spectrum = None
    processor.spectrum_seq = 0
    return {
        "status": "ok",
        "message": f"Spectrum input changed to '{tag}'. Waiting for new window...",
        "tag_fft": processor.cfg.tag_fft,
    }


@app.get("/spectrum/data")
def get_spectrum_data():
    if processor.last_spectrum is None:
        raise HTTPException(status_code=404, detail="Spectrum not ready yet")
    spec = processor.last_spectrum
    return {
        "fs": spec.fs,
        "scale": spec.scale,
        "freqs_hz": spec.freqs_hz.tolist(),
        "magnitudes": spec.magnitudes.tolist(),
        "seq": processor.spectrum_seq,
        "tag": processor.cfg.tag_fft,
    }


# Envelope
@app.get("/envelope/select/{tag}")
def set_envelope_tag(tag: str):
    processor.cfg.tag_env = tag
    processor.env_buffer.clear()
    processor.last_envelope = None
    processor.envelope_seq = 0
    return {
        "status": "ok",
        "message": f"Envelope input changed to '{tag}'. Waiting for new window...",
        "tag_env": processor.cfg.tag_env,
    }


@app.get("/envelope/data")
def get_envelope_data():
    if processor.last_envelope is None:
        raise HTTPException(status_code=404, detail="Envelope not ready yet")
    env = processor.last_envelope
    return {
        "fs": env.fs,
        "high_pass_hz": env.high_pass_hz,
        "low_pass_hz": env.low_pass_hz,
        "envelope": env.envelope.tolist(),
        "seq": processor.envelope_seq,
        "tag": processor.cfg.tag_env,
    }


# Waveform
@app.get("/waveform/select/{tag}")
def set_waveform_tag(tag: str):
    processor.cfg.tag_wave = tag
    processor.wave_buffer.clear()
    processor.last_waveform = None
    processor.wave_seq = 0
    return {
        "status": "ok",
        "message": f"Waveform input changed to '{tag}'. Waiting new window...",
        "tag_wave": processor.cfg.tag_wave,
    }


@app.get("/waveform/data")
def get_waveform_data():
    if processor.last_waveform is None:
        raise HTTPException(status_code=404, detail="Waveform not ready yet")
    wf = processor.last_waveform
    return {
        "fs": wf.fs,
        "cutoff_hz": wf.cutoff_hz,
        "seq": processor.wave_seq,
        "tag": processor.cfg.tag_wave,
        "time_s": wf.time_s.tolist(),
        "accel": wf.accel.tolist(),
        "velocity": wf.velocity.tolist() if wf.velocity is not None else None,
        "displacement": wf.displacement.tolist() if wf.displacement is not None else None,
    }


@app.websocket("/ws/ctrlx")
async def ws_ctrlx(websocket: WebSocket):
    await websocket_endpoint(websocket)
