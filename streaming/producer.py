import os
import time
import json
import uuid
import random
from kafka import KafkaProducer
from kafka.errors import KafkaError

def connect_kafka():
    broker = os.environ.get('KAFKA_BROKER', 'localhost:9092')
    for attempt in range(3):
        try:
            print(f"Connecting to Kafka at {broker} (Attempt {attempt+1}/3)")
            producer = KafkaProducer(
                bootstrap_servers=broker,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            print("Successfully connected to Kafka")
            return producer
        except KafkaError as e:
            print(f"Kafka connection error: {e}")
            if attempt < 2:
                time.sleep(5)
            else:
                raise

def generate_transaction():
    is_fraud_sim = random.random() < 0.05
    
    transaction = {
        'transaction_id': str(uuid.uuid4()),
        'TransactionAmt': random.uniform(3000, 5000) if is_fraud_sim else random.uniform(1, 5000),
        'ProductCD': random.choice(['W', 'H', 'C', 'S', 'R']),
        'card4': random.choice(['visa', 'mastercard', 'discover', 'american express']),
        'card6': random.choice(['debit', 'credit']),
        'P_emaildomain': random.choice(['gmail.com', 'yahoo.com', 'hotmail.com', 'anonymous.com']),
        'R_emaildomain': random.choice(['gmail.com', 'yahoo.com', 'hotmail.com', 'anonymous.com']),
        'addr1': random.uniform(100, 500),
        'addr2': random.uniform(10, 100),
        'dist1': random.uniform(0, 1000) if random.random() > 0.3 else None
    }
    
    # C1-C14
    for i in range(1, 15):
        transaction[f'C{i}'] = random.uniform(0, 100)
        
    # D1-D15
    for i in range(1, 16):
        transaction[f'D{i}'] = random.uniform(0, 500) if random.random() > 0.4 else None
        
    # M1-M9
    for i in range(1, 10):
        transaction[f'M{i}'] = random.choice(['T', 'F']) if random.random() > 0.2 else None
        
    # V1-V50
    for i in range(1, 51):
        transaction[f'V{i}'] = random.uniform(0, 1) if random.random() > 0.3 else None

    # suspicious patterns for simulated fraud
    if is_fraud_sim:
        transaction['ProductCD'] = 'C'
        transaction['P_emaildomain'] = 'anonymous.com'
        for i in range(1, 15):
            transaction[f'C{i}'] = random.uniform(80, 100) # High counts
        
    return transaction

def main():
    producer = connect_kafka()
    topic = os.environ.get('KAFKA_TOPIC', 'transactions')
    
    count = 0
    print(f"Starting to produce messages to topic: {topic}")
    try:
        while True:
            tx = generate_transaction()
            producer.send(topic, tx)
            
            count += 1
            if count % 10 == 0:
                print(f"Produced 10 messages. Latest transaction_id: {tx['transaction_id']}")
                
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping producer...")
    finally:
        producer.close()

if __name__ == "__main__":
    main()
