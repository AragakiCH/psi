# services/edge_ingest/src/ctrlx/influx_writer.py
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

        # Crea el bucket si no existe (útil para "features")
        try:
            buckets_api = self.client.buckets_api()
            bucket = buckets_api.find_bucket_by_name(cfg.bucket)
            if bucket is None:
                orgs_api = self.client.organizations_api()
                org = orgs_api.find_organizations(org=cfg.org)[0]
                buckets_api.create_bucket(bucket_name=cfg.bucket, org_id=org.id)
        except Exception:
            # Si falla (por ejemplo, falta permiso), simplemente lo ignoramos
            pass

    def write_telemetry(self, asset_id: str, signal_name: str,
                        value: float, ts_ns: int | None = None):
        p = (
            Point("telemetry")
            .tag("asset", asset_id)
            .tag("signal", signal_name)
            .field("value", float(value))
        )
        if ts_ns is not None:
            p.time(ts_ns)  # timestamp opcional
        self.write_api.write(bucket=self.cfg.bucket, org=self.cfg.org, record=p)

    def write_feature(self, asset_id: str, feature_name: str,
                      value: float, ts_ns: int | None = None):
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
        except Exception:
            pass
