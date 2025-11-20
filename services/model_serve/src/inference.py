from typing import Dict, Any


class Predictor:
    """
    Predictor dummy por ahora.
    Luego aquí cargas tu modelo real (ONNX / MLflow / Torch, etc.).
    """

    def __init__(self) -> None:
        # aquí podrías cargar el modelo desde MLflow, ONNX, etc.
        self.model_name = "dummy_v0"

    def predict(
        self,
        features: Dict[str, float],
        asset_id: str | None = None,
    ) -> Dict[str, Any]:
        # lógica dummy solo para probar el API
        score = sum(features.values()) / max(len(features), 1)
        label = "ok" if score < 1.0 else "alert"

        return {
            "label": label,
            "score": float(score),
            "model": self.model_name,
            "explain": None,
        }
