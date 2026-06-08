# pip install xgboost optuna mlflow shap scikit-learn pandas joblib matplotlib
import pandas as pd
import numpy as np
import xgboost as xgb
import optuna
import mlflow
import shap
import joblib
import json
import matplotlib.pyplot as plt
import os
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, confusion_matrix, ConfusionMatrixDisplay
import warnings

warnings.filterwarnings('ignore')

def main():
    # Setup paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base_dir, 'train_transaction.csv')
    
    print(f"Loading data from {data_path}...")
    df = pd.read_csv(data_path)
    
    # Target and features
    target_col = 'isFraud'
    
    # Drop columns
    cols_to_drop = ['TransactionID', 'TransactionDT']
    df = df.drop(columns=[col for col in cols_to_drop if col in df.columns])
    
    # Separate target
    y = df[target_col]
    X = df.drop(columns=[target_col])
    
    # Identify column types
    numeric_columns = X.select_dtypes(include=['int64', 'float64']).columns.tolist()
    categorical_columns = X.select_dtypes(include=['object', 'category']).columns.tolist()
    
    print("Preprocessing data...")
    # Preprocessing info dict
    preprocessing_info = {
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "median_values": {}
    }
    
    # Fill numeric nulls with median
    for col in numeric_columns:
        median_val = float(X[col].median())
        if pd.isna(median_val):
            median_val = 0.0
        preprocessing_info["median_values"][col] = median_val
        X[col] = X[col].fillna(median_val)
        
    # Fill categorical nulls and LabelEncode
    label_encoders = {}
    for col in categorical_columns:
        X[col] = X[col].fillna("missing")
        X[col] = X[col].astype(str)
        le = LabelEncoder()
        X[col] = le.fit_transform(X[col])
        label_encoders[col] = le
        
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42
    )
    
    print("Starting hyperparameter tuning with Optuna...")
    
    def objective(trial):
        params = {
            'n_estimators': trial.suggest_int('n_estimators', 100, 500),
            'max_depth': trial.suggest_int('max_depth', 3, 8),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3),
            'subsample': trial.suggest_float('subsample', 0.6, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
            'scale_pos_weight': trial.suggest_float('scale_pos_weight', 1.0, 10.0),
            'random_state': 42,
            'eval_metric': 'auc',
            'early_stopping_rounds': 50
        }
        
        model = xgb.XGBClassifier(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False
        )
        
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_pred_proba)
        return auc

    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=30)
    
    best_params = study.best_params
    print(f"Best params: {best_params}")
    
    print("Training final model with best parameters...")
    final_params = best_params.copy()
    final_params['random_state'] = 42
    final_params['eval_metric'] = 'auc'
    
    mlflow.set_experiment("fraud-detection")
    
    with mlflow.start_run():
        mlflow.log_params(best_params)
        
        final_model = xgb.XGBClassifier(**final_params)
        final_model.fit(X_train, y_train)
        
        y_pred = final_model.predict(X_test)
        y_pred_proba = final_model.predict_proba(X_test)[:, 1]
        
        # Metrics
        roc_auc = roc_auc_score(y_test, y_pred_proba)
        f1 = f1_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred)
        recall = recall_score(y_test, y_pred)
        
        mlflow.log_metrics({
            "roc_auc": roc_auc,
            "f1_score": f1,
            "precision": precision,
            "recall": recall
        })
        
        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)
        disp = ConfusionMatrixDisplay(confusion_matrix=cm)
        fig, ax = plt.subplots(figsize=(8, 6))
        disp.plot(ax=ax, cmap='Blues')
        plt.title('Confusion Matrix')
        cm_path = os.path.join(base_dir, 'confusion_matrix.png')
        plt.savefig(cm_path)
        plt.close()
        
        mlflow.log_artifact(cm_path)
        
        # SHAP
        print("Calculating SHAP values...")
        X_test_sampled = X_test.sample(n=min(1000, len(X_test)), random_state=42)
        explainer = shap.TreeExplainer(final_model)
        
        shap_values_raw = explainer.shap_values(X_test_sampled)
        if isinstance(shap_values_raw, list):
            shap_values = shap_values_raw[1]
        else:
            shap_values = shap_values_raw
            
        shap.summary_plot(shap_values, X_test_sampled, show=False)
        shap_path = os.path.join(base_dir, 'shap_summary.png')
        plt.savefig(shap_path, bbox_inches='tight')
        plt.close()
        
        # Top 10 feature importances
        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        feature_importance_df = pd.DataFrame({
            'feature': X_test_sampled.columns,
            'importance': mean_abs_shap
        }).sort_values(by='importance', ascending=False)
        
        top_10_features = feature_importance_df.head(10).set_index('feature')['importance'].to_dict()
        top_10_path = os.path.join(base_dir, 'feature_importance.json')
        with open(top_10_path, 'w') as f:
            json.dump(top_10_features, f, indent=4)
            
        # Model saving
        joblib.dump(final_model, os.path.join(base_dir, 'fraud_model.pkl'))
        
        with open(os.path.join(base_dir, 'feature_columns.json'), 'w') as f:
            json.dump(list(X.columns), f, indent=4)
            
        joblib.dump(label_encoders, os.path.join(base_dir, 'label_encoders.pkl'))
        
        with open(os.path.join(base_dir, 'preprocessing_info.json'), 'w') as f:
            json.dump(preprocessing_info, f, indent=4)
            
        print("\nPipeline completed successfully!")
        print(f"Final Test ROC-AUC: {roc_auc:.4f}")
        print(f"Final Test F1 Score: {f1:.4f}")

if __name__ == "__main__":
    main()
