from prefect import flow, task
import mlflow

@task
def train_model(ds_path: str) -> str:
    with mlflow.start_run():
        # carga datos, entrena, loggea métrica y artefactos
        mlflow.sklearn.log_model(model, "model")
        return mlflow.active_run().info.run_id

@flow
def train_and_register():
    run_id = train_model("/minio/datasets/motors.parquet")
    mlflow.register_model(f"runs:/{run_id}/model", "motor_predictor")
