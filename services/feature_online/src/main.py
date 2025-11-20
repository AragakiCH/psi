import time
from psi_sdk.io_kafka import KafkaConsumer, KafkaProducer
from psi_sdk.feature_store import FeastOnline
from psi_sdk.events import TelemetryV1, FeaturesV1

consumer = KafkaConsumer("clean.telemetry.v1")
producer = KafkaProducer("features.asset.v1")
feast = FeastOnline()

WINDOW = 60  # s

buffers: dict[str, list[TelemetryV1]] = {}

def compute_features(samples: list[TelemetryV1]) -> dict[str, float]:
    vals = [s.value for s in samples]
    n = max(1, len(vals))
    mean = sum(vals)/n
    # agrega rms, kurtosis, etc.
    return {"mean": mean}

for msg in consumer.iter():
    t: TelemetryV1 = TelemetryV1.model_validate_json(msg.value())
    key = f"{t.assetId}:{t.sensor}"
    buffers.setdefault(key, []).append(t)
    now = time.time()
    # purga ventana
    buffers[key] = [s for s in buffers[key] if now - s.ts_epoch <= WINDOW]
    # publicar cada N muestras
    if len(buffers[key]) >= 20:
        feats = compute_features(buffers[key])
        producer.send(FeaturesV1(assetId=t.assetId, window="60s", features=feats).model_dump_json())
        feast.write_online(t.assetId, feats)
