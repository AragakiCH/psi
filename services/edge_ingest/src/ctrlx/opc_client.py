import threading
import time
import logging
from typing import Optional, Callable, Dict, List, Tuple

from opcua import Client, ua

log = logging.getLogger("ctrlx.plc")


class PLCReader:
    """
    Lector OPC UA robusto:
    - Conecta, navega a PLC_PRG por BrowseName
    - Descubre variables bajo PLC_PRG
    - Lee en ciclo y emite dict por tipo + timestamp
    - Si PLC cae / red cae => reconecta con backoff
    """

    def __init__(
        self,
        url: str,
        user: Optional[str],
        password: Optional[str],
        buffer: List[Dict],
        buffer_size: int = 1000,
        period_s: float = 0.1,
        on_sample: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        self.url = url
        self.user = user or ""
        self.password = password or ""
        self.buffer = buffer
        self.buffer_size = buffer_size
        self.period_s = float(period_s)
        self.on_sample = on_sample

        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------- helpers ----------------

    def read_value(self, node):
        """Compatibilidad con DataLayer: intenta leer hijo '2:Value' primero."""
        try:
            val_node = node.get_child(["2:Value"])
            return val_node.get_value()
        except Exception:
            return node.get_value()

    def browse_by_names(self, root, *names):
        """Navega usando BrowseName.Name. Si no encuentra, devuelve None."""
        cur = root
        for n in names:
            found = None
            try:
                children = cur.get_children()
            except Exception as e:
                log.error("No pude listar hijos en %s: %s", cur, e)
                return None

            for ch in children:
                try:
                    bn = ch.get_browse_name().Name
                except Exception:
                    continue
                if bn == n:
                    found = ch
                    break

            if not found:
                log.error("No se encontró segmento '%s'. Revisa símbolos publicados en ctrlX.", n)
                return None

            cur = found
        return cur

    def _trim_buffer(self):
        try:
            while len(self.buffer) >= self.buffer_size:
                self.buffer.pop(0)
        except Exception:
            pass

    @staticmethod
    def _is_connection_drop(exc: Exception) -> bool:
        """
        Decide si un error debería disparar reconexión.
        En planta: si hay dudas, reconecta.
        """
        msg = str(exc)
        needles = [
            "WinError 10053",              # conexión abortada
            "WinError 10054",              # connection reset
            "BadSessionIdInvalid",         # sesión inválida
            "BadConnectionClosed",         # opcua status
            "BadSessionClosed",
            "Connection refused",
            "timed out",
            "Timeout",
            "socket",
            "Broken pipe",
        ]
        return any(n in msg for n in needles)

    def _discover_vars(self, plc_prg) -> List[Tuple[str, str, object]]:
        type_name_map = {
            "Boolean": "BOOL",
            "SByte": "SINT",
            "Byte": "BYTE",
            "Int16": "INT",
            "UInt16": "UINT",
            "Int32": "DINT",
            "UInt32": "UDINT",
            "Int64": "LINT",
            "UInt64": "ULINT",
            "Float": "REAL",
            "Double": "LREAL",
            "String": "STRING",
        }

        nodes = plc_prg.get_children()
        var_infos = []
        for ch in nodes:
            name = ch.get_browse_name().Name
            try:
                vt = ua.VariantType(ch.get_data_type_as_variant_type()).name
            except Exception:
                vt = "UNKNOWN"
            var_infos.append((name, type_name_map.get(vt, vt), ch))
        return var_infos

    # ---------------- loop principal ----------------

    def _loop(self) -> None:
        backoff = 2.0
        backoff_max = 30.0

        while not self._stop_evt.is_set():
            cli = None
            try:
                log.info("Conectando a OPC UA %s", self.url)
                cli = Client(self.url, timeout=3.0)
                if self.user:
                    cli.set_user(self.user)
                    cli.set_password(self.password)

                cli.connect()
                log.info("Conectado a OPC UA")
                backoff = 2.0  # reset backoff al conectar

                root = cli.get_root_node()
                plc_prg = self.browse_by_names(
                    root,
                    "Objects",
                    "Datalayer",
                    "plc",
                    "app",
                    "Application",
                    "sym",
                    "PLC_PRG",
                )

                if plc_prg is None:
                    # símbolo no publicado / ruta distinta
                    log.error("No encontré PLC_PRG. Reintentando en 5s…")
                    time.sleep(5.0)
                    continue

                var_infos = self._discover_vars(plc_prg)
                log.info("Descubiertas %d variables bajo PLC_PRG", len(var_infos))

                # loop de lectura
                while not self._stop_evt.is_set():
                    vars_by_type: Dict[str, Dict[str, object]] = {}

                    for name, plc_type_name, node in var_infos:
                        try:
                            val = self.read_value(node)
                            bucket = vars_by_type.setdefault(plc_type_name, {})
                            bucket[name] = val
                        except Exception as e:
                            if self._is_connection_drop(e):
                                raise  # fuerza reconexión global
                            err_bucket = vars_by_type.setdefault("Error", {})
                            err_bucket[name] = f"⛔ {e}"

                    vars_by_type["timestamp"] = time.time()

                    # buffer + callback (una sola vez, no duplicado)
                    self._trim_buffer()
                    self.buffer.append(vars_by_type)

                    if self.on_sample:
                        try:
                            self.on_sample(dict(vars_by_type))
                        except Exception as e:
                            log.warning("on_sample error: %s", e)

                    time.sleep(self.period_s)

            except Exception as e:
                # cualquier error serio => reconectar
                log.error("OPC UA loop error: %s", e)

                # backoff progresivo
                time.sleep(backoff)
                backoff = min(backoff * 1.7, backoff_max)

            finally:
                if cli is not None:
                    try:
                        cli.disconnect()
                    except Exception:
                        pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
