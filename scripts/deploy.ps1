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

    # 5. Install Kafka via Helm if not already installed
    Write-Host "Checking if Kafka is installed..."
    $releaseStatus = helm status kafka 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Kafka already installed"
    } else {
        Write-Host "Installing Kafka via Helm..."
        helm install kafka bitnami/kafka -n default --set replicaCount=1 --set controller.replicaCount=1 --set broker.replicaCount=0 --set persistence.enabled=false --set kraft.enabled=true
        if ($LASTEXITCODE -ne 0) { throw "Failed to install Kafka" }
    }

    # 6. Install Redis via Helm if not already installed
    Write-Host "Checking if Redis is installed..."
    $releaseStatus = helm status redis 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Redis already installed"
    } else {
        Write-Host "Installing Redis via Helm..."
        helm install redis bitnami/redis -n default --set architecture=standalone --set auth.enabled=false --set master.persistence.enabled=false
        if ($LASTEXITCODE -ne 0) { throw "Failed to install Redis" }
    }

    # 7. Install PostgreSQL via Helm if not already installed
    Write-Host "Checking if PostgreSQL is installed..."
    $releaseStatus = helm status postgresql 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PostgreSQL already installed"
    } else {
        Write-Host "Installing PostgreSQL via Helm..."
        helm install postgresql bitnami/postgresql -n default --set auth.postgresPassword=postgres --set auth.database=fraud_db --set primary.persistence.enabled=false
        if ($LASTEXITCODE -ne 0) { throw "Failed to install PostgreSQL" }
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
