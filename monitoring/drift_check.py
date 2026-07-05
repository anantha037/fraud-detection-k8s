# pip install evidently pandas numpy
# Evidently 0.7.x compatible drift monitoring script

import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def load_feature_info():
    base = Path(__file__).parent.parent / "model"
    with open(base / "feature_columns.json") as f:
        feature_columns = json.load(f)
    with open(base / "preprocessing_info.json") as f:
        info = json.load(f)
    return feature_columns, info

def generate_reference(feature_columns, info, n=500):
    data = {}
    for col in feature_columns:
        if col in info["numeric_columns"]:
            median = info["median_values"].get(col, 1.0) or 1.0
            data[col] = np.random.normal(loc=median, scale=abs(median) * 0.1 + 0.01, size=n)
        else:
            data[col] = ["common_value"] * n
    return pd.DataFrame(data)

def generate_current(feature_columns, info, n=200):
    data = {}
    drift_mask = np.random.random(n) < 0.3
    for col in feature_columns:
        if col in info["numeric_columns"]:
            median = info["median_values"].get(col, 1.0) or 1.0
            base = np.random.normal(loc=median, scale=abs(median) * 0.1 + 0.01, size=n)
            drift_factor = np.where(drift_mask, np.random.uniform(2, 5, n), 1.0)
            data[col] = base * drift_factor
        else:
            data[col] = np.where(drift_mask, "drift_value", "common_value")
    return pd.DataFrame(data)

def main():
    logger.info("Loading feature info...")
    feature_columns, info = load_feature_info()

    logger.info("Generating reference dataset (500 rows)...")
    reference = generate_reference(feature_columns, info)

    logger.info("Generating current dataset with drift (200 rows)...")
    current = generate_current(feature_columns, info)

    logger.info("Running drift analysis...")

    # Numeric columns only for drift detection
    numeric_cols = [c for c in feature_columns if c in info["numeric_columns"]]
    
    drifted = 0
    drift_details = {}
    for col in numeric_cols:
        ref_mean = reference[col].mean()
        cur_mean = current[col].mean()
        ratio = abs(cur_mean - ref_mean) / (abs(ref_mean) + 1e-9)
        is_drifted = ratio > 0.2
        if is_drifted:
            drifted += 1
        drift_details[col] = {"drifted": is_drifted, "ratio": round(ratio, 4)}

    drift_share = drifted / len(numeric_cols) if numeric_cols else 0.0
    drift_detected = drift_share > 0.2

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_columns": len(feature_columns),
        "numeric_columns_checked": len(numeric_cols),
        "drifted_columns": drifted,
        "drift_detected": drift_detected,
        "drift_share": round(drift_share, 4)
    }

    # Save JSON summary
    out_dir = Path(__file__).parent
    summary_path = out_dir / "drift_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Drift summary saved to {summary_path}")

    # Save simple HTML report
    report_path = out_dir / "drift_report.html"
    html = f"""<html><body>
    <h1>Fraud Detection - Drift Report</h1>
    <p>Generated: {summary['timestamp']}</p>
    <p>Drift detected: <b>{drift_detected}</b></p>
    <p>Drifted columns: {drifted} / {len(numeric_cols)}</p>
    <p>Drift share: {drift_share:.2%}</p>
    <h2>Per-column drift (sample)</h2>
    <table border=1>
    <tr><th>Column</th><th>Drifted</th><th>Mean ratio</th></tr>
    {''.join(f"<tr><td>{c}</td><td>{v['drifted']}</td><td>{v['ratio']}</td></tr>" for c,v in list(drift_details.items())[:20])}
    </table>
    </body></html>"""
    with open(report_path, "w") as f:
        f.write(html)
    logger.info(f"Drift report saved to {report_path}")

    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()