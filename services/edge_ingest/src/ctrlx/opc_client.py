import threading
import time
import logging
from typing import Optional, Callable, Dict, List

from opcua import Client, ua

log = logging.getLogger("ctrlx.plc")


class PLCReader:
    """
    Lector OPC UA para ctrlX, basado en tu proyecto WebSocket_RX.

    - Navega por BrowseName:
      Objects → Datalayer → plc → app → Application → sym → PLC_PRG
    - Descubre TODAS las variables debajo de PLC_PRG.
    - En cada ciclo lee todas, las agrupa por tipo PLC (BOOL, INT, REAL, etc.)
      y mete un dict en el buffer:

      {
        "BOOL": { var_name: value, ... },
        "INT":  { ... },
        ...
        "timestamp": <epoch_seconds>
      }
    """

    def __init__(
        self,
        url: str,
        user: Optional[str],
        password: Optional[str],
        buffer,
        buffer_size: int = 1000,
        period_s: float = 0.1,
        on_sample: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        self.url = url
        self.user = user or ""
        self.password = password or ""
        self.buffer = buffer
        self.buffer_size = buffer_size
        self.period_s = period_s
        self.on_sample = on_sample
        self._stop = False

    # ---------------- helpers ----------------

    def read_value(self, node):
        """Compatibilidad con DataLayer: intenta leer hijo '2:Value' primero."""
        try:
            val_node = node.get_child(["2:Value"])
            return val_node.get_value()
        except Exception:
            return node.get_value()
        
    

    def browse_by_names(self, root, *names):
        """
        Navega usando BrowseName.Name, como en tu código viejo.
        Si no encuentra un segmento, devuelve None.
        """
        cur = root
        for n in names:
            found = None
            for ch in cur.get_children():
                try:
                    bn = ch.get_browse_name().Name
                except Exception:
                    continue
                if bn == n:
                    found = ch
                    break
            if not found:
                log.error("No se encontró segmento '%s' debajo de %s", n, cur)
                log.error("Por favor publica un proyecto desde la configuración de símbolos")
                return None
            cur = found
        return cur

    # ---------------- loop principal ----------------

    def _loop(self) -> None:
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

        while not self._stop:
            cli = None
            try:
                log.info("Conectando a OPC UA %s", self.url)
                cli = Client(self.url, timeout=3.0)
                if self.user:
                    cli.set_user(self.user)
                    cli.set_password(self.password)
                cli.connect()
                log.info("Conectado a OPC UA")

                root = cli.get_root_node()
                # 🔥 MISMO PATH QUE EN TU PROYECTO ANTIGUO
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
                    # espera un rato y reintenta
                    time.sleep(5.0)
                    continue

                nodes = plc_prg.get_children()
                var_infos = []
                for ch in nodes:
                    name = ch.get_browse_name().Name
                    try:
                        vt = ua.VariantType(ch.get_data_type_as_variant_type()).name
                    except Exception:
                        vt = "UNKNOWN"
                    var_infos.append((name, type_name_map.get(vt, vt), ch))

                log.info("Descubiertas %d variables bajo PLC_PRG:", len(var_infos))
                for name, plc_type_name, _ in var_infos:
                    log.info("  %s (%s)", name, plc_type_name)

                while not self._stop:
                    vars_by_type: Dict[str, Dict[str, object]] = {}
                    fatal_error = False

                    for name, plc_type_name, node in var_infos:
                        try:
                            val = self.read_value(node)
                            bucket = vars_by_type.setdefault(plc_type_name, {})
                            bucket[name] = val
                        except Exception as e:
                            msg = str(e)
                            # 🔥 si la conexión OPC UA se cae, marcamos para reconectar
                            if "WinError 10053" in msg or "BadSessionIdInvalid" in msg:
                                log.error("Conexión OPC UA abortada, forzando reconexión: %s", msg)
                                fatal_error = True
                                break
                            err_bucket = vars_by_type.setdefault("Error", {})
                            err_bucket[name] = f"⛔ {e}"

                    if fatal_error:
                        # dejamos que el try/except exterior maneje el reconnect
                        raise Exception("OPC UA connection dropped (WinError 10053)")

                    vars_by_type["timestamp"] = time.time()

                    # poda del buffer
                    try:
                        while len(self.buffer) >= self.buffer_size:
                            self.buffer.pop(0)
                    except Exception:
                        pass

                    self.buffer.append(vars_by_type)

                    if self.on_sample:
                        try:
                            self.on_sample(dict(vars_by_type))
                        except Exception as e:
                            log.warning("on_sample error: %s", e)

                    time.sleep(self.period_s)

                    # poda por tamaño propio
                    try:
                        while len(self.buffer) >= self.buffer_size:
                            self.buffer.pop(0)
                    except Exception:
                        pass

                    self.buffer.append(vars_by_type)

                    if self.on_sample:
                        try:
                            self.on_sample(dict(vars_by_type))
                        except Exception as e:
                            log.warning("on_sample error: %s", e)

                    time.sleep(self.period_s)

            except Exception as e:
                log.error("Error en loop OPC UA: %s", e)
                time.sleep(2.0)
            finally:
                if cli is not None:
                    try:
                        cli.disconnect()
                    except Exception:
                        pass

    def start(self) -> None:
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop = True
