from pydantic import BaseModel


class InferRequest(BaseModel):
    assetId: str
    features: dict[str, float]


class InferResponse(BaseModel):
    label: str
    score: float
    model: str
    explain: dict | None = None
