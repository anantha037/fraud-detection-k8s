"""
Load test for the fraud detection K8s deployment.
"""
import os
import random
import uuid
import logging
from locust import HttpUser, task, between

class FraudDetectionUser(HttpUser):
    wait_time = between(0.5, 2)
    host = os.environ.get("LOCUST_HOST", "http://127.0.0.1:65144")

    def on_start(self):
        logging.info("Starting load test user")

    @task(3)
    def predict_legitimate(self):
        payload = {
            "TransactionAmt": random.uniform(10, 500),
            "ProductCD": random.choice(["W", "H"]),
            "card4": random.choice(["visa", "mastercard"]),
            "card6": "debit",
            "P_emaildomain": random.choice(["gmail.com", "yahoo.com"]),
            "transaction_id": str(uuid.uuid4())
        }
        
        # We do not use catch_response=True here so Locust naturally handles stats
        response = self.client.post("/predict", json=payload)
        
        if response.status_code != 200:
            logging.error(f"Legitimate prediction failed with status code: {response.status_code}")

    @task(1)
    def predict_fraudulent(self):
        payload = {
            "TransactionAmt": random.uniform(3000, 5000),
            "ProductCD": "C",
            "card4": "american express",
            "card6": "credit",
            "P_emaildomain": "anonymous.com",
            "transaction_id": str(uuid.uuid4())
        }
        
        response = self.client.post("/predict", json=payload)
        
        if response.status_code == 200:
            try:
                result = response.json()
                if result.get("is_fraud") is True:
                    logging.info(f"Fraud detected successfully for transaction: {payload['transaction_id']}")
            except Exception as e:
                logging.error(f"Failed to parse JSON response: {e}")
        else:
            logging.error(f"Fraudulent prediction failed with status code: {response.status_code}")

    @task(1)
    def health_check(self):
        self.client.get("/health")
