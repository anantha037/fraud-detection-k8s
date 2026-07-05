# pip install evidently pandas
import os
import json
import logging
import random
import datetime
from pathlib import Path
import pandas as pd
import numpy as np

from evidently.report import Report
from evidently.metrics import DatasetSummaryMetric, DataDriftTable, DatasetMissingValuesSummary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Data Drift Monitoring Check")
    
    # Paths
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    model_dir = base_dir / "model"
    monitoring_dir = base_dir / "monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    
    # Load info
    preprocessing_path = model_dir / "preprocessing_info.json"
    feature_columns_path = model_dir / "feature_columns.json"
    
    with open(preprocessing_path, "r") as f:
        prep_info = json.load(f)
        
    with open(feature_columns_path, "r") as f:
        feature_columns = json.load(f)
        
    numeric_cols = prep_info["numeric_columns"]
    categorical_cols = prep_info["categorical_columns"]
    median_values = prep_info["median_values"]
    
    # Generate reference dataset (500 rows)
    logger.info("Generating reference dataset (500 rows)")
    ref_data = {}
    for col in feature_columns:
        if col in numeric_cols:
            median = median_values.get(col, 0.0)
            # Use small noise if median is exactly 0
            std = abs(median) * 0.1 if median != 0 else 0.1
            ref_data[col] = np.random.normal(loc=median, scale=std, size=500)
        elif col in categorical_cols:
            # Simulate most common value
            ref_data[col] = ["common_value"] * 500
        else:
            ref_data[col] = [0] * 500
            
    reference_df = pd.DataFrame(ref_data)
    
    # Generate current dataset (200 rows)
    logger.info("Generating current dataset (200 rows) with 30% drift")
    curr_data = {}
    n_total = 200
    n_drift = int(n_total * 0.3)
    n_normal = n_total - n_drift
    
    for col in feature_columns:
        if col in numeric_cols:
            median = median_values.get(col, 0.0)
            std = abs(median) * 0.1 if median != 0 else 0.1
            
            # Normal distribution part
            normal_part = np.random.normal(loc=median, scale=std, size=n_normal)
            
            # Drifted part (multiply by random factor 2-5x)
            factor = np.random.uniform(2, 5, size=n_drift)
            drift_part = np.random.normal(loc=median, scale=std, size=n_drift) * factor
            
            curr_col = np.concatenate([normal_part, drift_part])
            np.random.shuffle(curr_col)
            curr_data[col] = curr_col
            
        elif col in categorical_cols:
            normal_part = ["common_value"] * n_normal
            drift_part = [random.choice(["drift_A", "drift_B", "drift_C"]) for _ in range(n_drift)]
            
            curr_col = np.array(normal_part + drift_part)
            np.random.shuffle(curr_col)
            curr_data[col] = curr_col
        else:
            curr_data[col] = [0] * n_total
            
    current_df = pd.DataFrame(curr_data)
    
    logger.info(f"Datasets generated. Reference size: {reference_df.shape}, Current size: {current_df.shape}")
    
    # Run Evidently Report
    logger.info("Running Evidently Drift Report...")
    report = Report(metrics=[
        DatasetSummaryMetric(),
        DataDriftTable(),
        DatasetMissingValuesSummary()
    ])
    
    report.run(reference_data=reference_df, current_data=current_df)
    
    # Save HTML report
    html_path = monitoring_dir / "drift_report.html"
    report.save_html(str(html_path))
    logger.info(f"Saved drift HTML report to {html_path}")
    
    # Extract JSON summary
    report_dict = report.as_dict()
    
    # Look for DataDriftTable metric results
    drift_result = None
    for metric in report_dict.get('metrics', []):
        if metric.get('metric') == 'DataDriftTable':
            drift_result = metric.get('result')
            break
            
    if drift_result:
        total_columns = drift_result.get('number_of_columns', len(feature_columns))
        drifted_columns = drift_result.get('number_of_drifted_columns', 0)
        drift_share = drift_result.get('share_of_drifted_columns', 0.0)
        drift_detected = drift_result.get('dataset_drift', False)
    else:
        # Fallback if structure changes
        total_columns = len(feature_columns)
        drifted_columns = 0
        drift_share = 0.0
        drift_detected = False
        
    summary = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "total_columns": total_columns,
        "drifted_columns": drifted_columns,
        "drift_detected": drift_detected,
        "drift_share": drift_share
    }
    
    # Save JSON summary
    json_path = monitoring_dir / "drift_summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=4)
        
    logger.info(f"Saved drift JSON summary to {json_path}")
    
    # Print final summary to console
    print("\n--- Final Drift Summary ---")
    print(json.dumps(summary, indent=4))
    
if __name__ == "__main__":
    main()
