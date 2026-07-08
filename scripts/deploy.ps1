$ErrorActionPreference = "Stop"

try {
    # 1. Start minikube with specific flags if not already running
    Write-Host "Checking if Minikube is already running..."
    $minikubeStatus = minikube status 2>&1 | Out-String
    if ($minikubeStatus -match "host: Running" -or $minikubeStatus -match "kubelet: Running") {
        Write-Host "Minikube already running"
    } else {
        Write-Host "Starting Minikube..."
        minikube start --memory=3072 --cpus=2 --driver=docker
        if ($LASTEXITCODE -ne 0) { throw "Failed to start Minikube" }
    }

    # 2. Enable minikube addons: metrics-server and ingress
    Write-Host "Enabling metrics-server addon..."
    minikube addons enable metrics-server
    if ($LASTEXITCODE -ne 0) { throw "Failed to enable metrics-server addon" }
    Write-Host "metrics-server enabled"

    Write-Host "Enabling ingress addon..."
    minikube addons enable ingress
    if ($LASTEXITCODE -ne 0) { throw "Failed to enable ingress addon" }
    Write-Host "ingress enabled"

    # 3. Load the local Docker image into minikube
    Write-Host "Loading Docker image into Minikube..."
    minikube image load fraud-detection-api:latest
    if ($LASTEXITCODE -ne 0) { throw "Failed to load image into Minikube" }
    Write-Host "Image loaded into minikube"

    # 4. Add Helm repos and update
    Write-Host "Adding bitnami Helm repository and updating..."
    helm repo add bitnami https://charts.bitnami.com/bitnami
    helm repo update
    if ($LASTEXITCODE -ne 0) { throw "Failed to add/update Helm repos" }

    # 5. Deploy Kafka using kubectl
    Write-Host "Checking if Kafka is installed..."
    $ErrorActionPreference = "Continue"
    kubectl get pod kafka 2>&1 | Out-Null
    $kafkaExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($kafkaExitCode -eq 0) {
        Write-Host "Kafka already running"
    } else {
        Write-Host "Starting Kafka..."
        kubectl run kafka --image=apache/kafka:3.7.0 --restart=Never --env="KAFKA_NODE_ID=1" --env="KAFKA_PROCESS_ROLES=broker,controller" --env="KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093" --env="KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092" --env="KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka:9093" --env="KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER" --env="KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT" --env="KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1" --port=9092
        if ($LASTEXITCODE -ne 0) { throw "Failed to start Kafka" }
        kubectl expose pod kafka --port=9092 --name=kafka
        if ($LASTEXITCODE -ne 0) { throw "Failed to expose Kafka" }
    }

    # 6. Install Redis via Helm if not already installed
    Write-Host "Checking if Redis is installed..."
    $ErrorActionPreference = "Continue"
    $releaseStatus = helm status redis 2>&1
    $redisExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($redisExitCode -eq 0) {
        Write-Host "Redis already installed"
    } else {
        Write-Host "Installing Redis via Helm..."
        helm install redis bitnami/redis -n default --set architecture=standalone --set auth.enabled=false --set master.persistence.enabled=false
        if ($LASTEXITCODE -ne 0) { throw "Failed to install Redis" }
    }

    # 7. Deploy PostgreSQL using kubectl
    Write-Host "Checking if PostgreSQL is installed..."
    $ErrorActionPreference = "Continue"
    kubectl get pod postgresql 2>&1 | Out-Null
    $pgExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($pgExitCode -eq 0) {
        Write-Host "PostgreSQL already running"
    } else {
        Write-Host "Starting PostgreSQL..."
        kubectl run postgresql --image=postgres:16-alpine --restart=Never --env="POSTGRES_PASSWORD=postgres" --env="POSTGRES_DB=fraud_db" --port=5432
        if ($LASTEXITCODE -ne 0) { throw "Failed to start PostgreSQL" }
        kubectl expose pod postgresql --port=5432 --name=postgresql
        if ($LASTEXITCODE -ne 0) { throw "Failed to expose PostgreSQL" }
    }

    # 8. Apply all Kubernetes manifests in order
    Write-Host "Applying Kubernetes manifests..."
    kubectl apply -f k8s/configmap.yaml
    kubectl apply -f k8s/deployment.yaml
    kubectl apply -f k8s/service.yaml
    kubectl apply -f k8s/hpa.yaml
    kubectl apply -f k8s/ingress.yaml
    if ($LASTEXITCODE -ne 0) { throw "Failed to apply Kubernetes manifests" }

    # 9. Wait for deployment rollout
    Write-Host "Waiting for deployment rollout..."
    kubectl rollout status deployment/fraud-detection-api --timeout=120s
    if ($LASTEXITCODE -ne 0) { throw "Deployment rollout failed or timed out" }

    # 10. Print final status
    Write-Host "Final status:"
    kubectl get pods
    kubectl get services
    kubectl get hpa
    Write-Host "Deployment complete. Access via: minikube service fraud-detection-service --url"

} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}