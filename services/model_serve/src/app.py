from fastapi import FastAPI, HTTPException

from .dto import InferRequest, InferResponse
from .inference import Predictor

app = FastAPI(title="psi-model-serve", version="0.1.0")

# instancia global del predictor
predictor = Predictor()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/infer", response_model=InferResponse)
def infer(req: InferRequest):
    try:
        result = predictor.predict(req.features, asset_id=req.assetId)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"inference_error: {e}")
