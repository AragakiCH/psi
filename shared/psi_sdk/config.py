from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    ctrlx_opcua_url: str = "opc.tcp://192.168.100.31:4840"
    ctrlx_opcua_user: str | None = None
    ctrlx_opcua_password: str | None = None
    ctrlx_opcua_period_s: float = 0.1

    # estos pueden existir pero ya no los usaremos:
    ctrlx_opcua_node_ids: str = ""
    ctrlx_opcua_root_path: str | None = None

    class Config:
        env_file = ".env"