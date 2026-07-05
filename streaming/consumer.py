import os
import time
import json
import logging
import requests
import redis
import psycopg2
from psycopg2.extras import Json
from kafka import KafkaConsumer

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def setup_db(db_url):
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fraud_predictions (
            id SERIAL PRIMARY KEY,
            transaction_id VARCHAR(36),
            fraud_probability FLOAT,
            is_fraud BOOLEAN,
            risk_level VARCHAR(10),
            raw_transaction JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

def get_pg_connection(db_url):
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    return conn

def main():
    kafka_broker = os.environ.get('KAFKA_BROKER', 'localhost:9092')
    kafka_topic = os.environ.get('KAFKA_TOPIC', 'transactions')
    inference_url = os.environ.get('INFERENCE_URL', 'http://localhost:8000')
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/fraud_db')
    
    # Init DB
    try:
        setup_db(db_url)
        pg_conn = get_pg_connection(db_url)
        logger.info("Connected to PostgreSQL and verified table")
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        return
        
    # Init Redis
    try:
        r = redis.from_url(redis_url)
        r.ping()
        logger.info("Connected to Redis")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return

    # Init Kafka
    consumer = KafkaConsumer(
        kafka_topic,
        bootstrap_servers=kafka_broker,
        group_id='fraud-detection-group',
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        auto_offset_reset='latest'
    )
    logger.info(f"Started Kafka consumer on topic {kafka_topic}")
    
    for message in consumer:
        start_time = time.time()
        transaction = message.value
        transaction_id = transaction.get('transaction_id')
        
        if not transaction_id:
            logger.warning("Message missing transaction_id, skipping")
            continue
            
        try:
            # 1. POST to /predict endpoint
            resp = requests.post(f"{inference_url}/predict", json=transaction, timeout=5)
            resp.raise_for_status()
            result = resp.json()
            
            # 2. Store in Redis
            r.setex(
                f"fraud:{transaction_id}",
                3600, # 1 hour TTL
                json.dumps(result)
            )
            
            # 3. Insert into PostgreSQL
            try:
                if pg_conn.closed != 0:
                    pg_conn = get_pg_connection(db_url)
                cursor = pg_conn.cursor()
            except Exception as db_err:
                logger.warning(f"Reconnecting to PostgreSQL due to error: {db_err}")
                pg_conn = get_pg_connection(db_url)
                cursor = pg_conn.cursor()
            cursor.execute(
                """
                INSERT INTO fraud_predictions 
                (transaction_id, fraud_probability, is_fraud, risk_level, raw_transaction)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    transaction_id,
                    result['fraud_probability'],
                    result['is_fraud'],
                    result['risk_level'],
                    Json(transaction)
                )
            )
            pg_conn.commit()
            cursor.close()
            
            # 4. If is_fraud=True, print FRAUD ALERT
            if result['is_fraud']:
                logger.warning(f"FRAUD ALERT! Transaction: {transaction_id}, Probability: {result['fraud_probability']:.4f}")
                
        except Exception as e:
            logger.error(f"Error processing transaction {transaction_id}: {e}")
            pg_conn.rollback() # reset aborted db transaction
            
        # 5. Log processing time
        process_time = time.time() - start_time
        logger.info(f"Processed {transaction_id} in {process_time:.4f} seconds")

if __name__ == "__main__":
    main()
