from feast import Entity, FeatureView, Field
from feast.types import Float32
from datetime import timedelta

asset = Entity(name="asset_id", join_keys=["asset_id"])

features_60s = FeatureView(
    name="telemetry_60s",
    entities=[asset],
    ttl=timedelta(days=7),
    schema=[Field(name="mean", dtype=Float32)],
    online=True,
    source=... # stream or batch source
)
