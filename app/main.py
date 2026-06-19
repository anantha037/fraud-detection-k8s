import os
import json
import joblib
import logging
import threading
from contextlib import asynccontextmanager
from typing import Optional, Union, Dict, Any, List

import pandas as pd
import numpy as np
import shap
from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from prometheus_fastapi_instrumentator import Instrumentator

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Global state / module-level variables
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE_DIR, "model")

model = None
feature_columns = None
label_encoders = None
preprocessing_info = None
explainer = None
model_loaded = False

# Metrics state
class MetricsContainer:
    def __init__(self):
        self.lock = threading.Lock()
        self.total_predictions = 0
        self.fraud_count = 0
        self.total_fraud_probability = 0.0
        
    def record(self, probability: float, is_fraud: bool):
        with self.lock:
            self.total_predictions += 1
            self.total_fraud_probability += probability
            if is_fraud:
                self.fraud_count += 1
                
    def summary(self):
        with self.lock:
            avg_prob = (self.total_fraud_probability / self.total_predictions) if self.total_predictions > 0 else 0.0
            return {
                "total_predictions": self.total_predictions,
                "fraud_count": self.fraud_count,
                "avg_fraud_probability": avg_prob
            }

app_metrics = MetricsContainer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, feature_columns, label_encoders, preprocessing_info, explainer, model_loaded
    # Load model and artifacts on startup
    try:
        logger.info("Loading model artifacts...")
        model = joblib.load(os.path.join(MODEL_DIR, "fraud_model.pkl"))
        
        with open(os.path.join(MODEL_DIR, "feature_columns.json"), "r") as f:
            feature_columns = json.load(f)
            
        label_encoders = joblib.load(os.path.join(MODEL_DIR, "label_encoders.pkl"))
        
        with open(os.path.join(MODEL_DIR, "preprocessing_info.json"), "r") as f:
            preprocessing_info = json.load(f)
            
        # Initialize SHAP explainer
        logger.info("Initializing SHAP explainer...")
        explainer = shap.TreeExplainer(model)
        
        model_loaded = True
        logger.info("Model artifacts loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load model artifacts: {e}")
        model_loaded = False
        
    yield
    # Cleanup on shutdown
    logger.info("Shutting down model service...")
    model_loaded = False

app = FastAPI(title="Fraud Detection API", lifespan=lifespan)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Pydantic models
class TransactionInput(BaseModel):
    # This allows arbitrary fields corresponding to 'all fields Optional[Union[float, str]] = None'
    model_config = ConfigDict(extra="allow")
    transaction_id: Optional[str] = "unknown"

class PredictionResponse(BaseModel):
    transaction_id: str
    fraud_probability: float
    is_fraud: bool
    risk_level: str
    shap_top_features: List[Dict[str, Union[str, float]]]

def preprocess_features(raw_features: dict) -> np.ndarray:
    # We will build a clean dict
    clean_features = {}
    
    numeric_cols = preprocessing_info["numeric_columns"]
    median_values = preprocessing_info["median_values"]
    
    for col in numeric_cols:
        val = raw_features.get(col)
        if val is None or val == "":
            clean_features[col] = median_values.get(col, 0.0)
        else:
            try:
                # Handle possible pd.NA
                if pd.isna(val):
                    clean_features[col] = median_values.get(col, 0.0)
                else:
                    clean_features[col] = float(val)
            except (ValueError, TypeError):
                clean_features[col] = median_values.get(col, 0.0)
                
    categorical_cols = preprocessing_info["categorical_columns"]
    
    for col in categorical_cols:
        val = raw_features.get(col)
        if val is None or val == "":
            str_val = "missing"
        else:
            try:
                if pd.isna(val):
                    str_val = "missing"
                else:
                    str_val = str(val)
            except (ValueError, TypeError):
                str_val = "missing"
            
        le = label_encoders.get(col)
        if le:
            if str_val not in le.classes_:
                str_val = "missing"
            # It's possible "missing" is also not in classes if it never appeared in training
            if str_val not in le.classes_:
                str_val = le.classes_[0] if len(le.classes_) > 0 else "0"
                
            try:
                clean_features[col] = le.transform([str_val])[0]
            except Exception:
                clean_features[col] = 0
        else:
            clean_features[col] = 0
            
    # Reorder columns exactly as in feature_columns
    ordered_features = {col: clean_features.get(col, 0) for col in feature_columns}
    df = pd.DataFrame([ordered_features])
    
    return df.values

@app.post("/predict", response_model=PredictionResponse)
async def predict(transaction: TransactionInput):
    if not model_loaded:
        raise HTTPException(status_code=503, detail="Model is not loaded")
        
    try:
        # Extra fields will be included in the dict natively in Pydantic v2
        raw_features = transaction.model_dump()
        
        # Extract transaction_id
        transaction_id = str(raw_features.pop("transaction_id", "unknown"))
            
        # Preprocess
        X_array = preprocess_features(raw_features)
        
        # Predict
        probability = float(model.predict_proba(X_array)[0, 1])
        is_fraud = probability >= 0.5
        
        # Risk level
        if probability >= 0.7:
            risk_level = "HIGH"
        elif probability >= 0.3:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
            
        # Record metrics
        app_metrics.record(probability, is_fraud)
        
        # SHAP
        shap_values_raw = explainer.shap_values(X_array)
        if isinstance(shap_values_raw, list):
            shap_vals = shap_values_raw[1][0]
        else:
            shap_vals = shap_values_raw[0]
            
        # Top 5 features by absolute SHAP value
        feature_importance = [
            {"feature": col, "shap_value": float(val)} 
            for col, val in zip(feature_columns, shap_vals)
        ]
        feature_importance.sort(key=lambda x: abs(x["shap_value"]), reverse=True)
        top_5_features = feature_importance[:5]
        
        logger.info(f"Prediction: transaction_id={transaction_id}, fraud_probability={probability:.4f}, is_fraud={is_fraud}")
        
        return PredictionResponse(
            transaction_id=transaction_id,
            fraud_probability=probability,
            is_fraud=is_fraud,
            risk_level=risk_level,
            shap_top_features=top_5_features
        )
        
    except Exception as e:
        logger.exception("Prediction failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model_loaded": model_loaded
    }

@app.get("/ready")
async def ready(response: Response):
    if model_loaded:
        response.status_code = status.HTTP_200_OK
        return {"status": "ready"}
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready"}

@app.get("/metrics/summary")
async def metrics_summary():
    return app_metrics.summary()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
