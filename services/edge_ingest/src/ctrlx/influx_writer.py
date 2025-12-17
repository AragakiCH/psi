from __future__ import annotations
from dataclasses import dataclass
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


@dataclass
class InfluxCfg:
    url: str
    token: str
    org: str
    bucket: str


class InfluxWriter:
    def __init__(self, cfg: InfluxCfg):
        self.cfg = cfg
        self.client = InfluxDBClient(url=cfg.url, token=cfg.token, org=cfg.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def write_telemetry(self, asset_id: str, signal_name: str, value: float, ts_ns: int | None = None):
        p = (
            Point("telemetry")
            .tag("asset", asset_id)
            .tag("signal", signal_name)
            .field("value", float(value))
        )
        if ts_ns is not None:
            p.time(ts_ns)  # timestamp opcional; si no pones, usa el “ahora”
        self.write_api.write(bucket=self.cfg.bucket, org=self.cfg.org, record=p)

    def write_feature(self, asset_id: str, feature_name: str, value: float, ts_ns: int | None = None):
        p = (
            Point("features")
            .tag("asset", asset_id)
            .tag("feature", feature_name)
            .field("value", float(value))
        )
        if ts_ns is not None:
            p.time(ts_ns)
        self.write_api.write(bucket=self.cfg.bucket, org=self.cfg.org, record=p)

    def close(self):
        try:
            self.client.close()
        except:
            pass
