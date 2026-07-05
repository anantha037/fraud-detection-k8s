<#
.SYNOPSIS
Teardown script for the fraud detection service on minikube.
#>

# 1. Delete all K8s manifests
Write-Host "Deleting all Kubernetes manifests in k8s/..."
kubectl delete -f k8s/ --ignore-not-found

# 2. Uninstall Helm releases if they exist
Write-Host "Uninstalling Helm releases..."
helm uninstall kafka --ignore-not-found
helm uninstall redis --ignore-not-found
helm uninstall postgresql --ignore-not-found

# 3. Remove the loaded image from minikube
Write-Host "Removing loaded image from Minikube..."
minikube image rm fraud-detection-api:latest

# 4. Optionally stop minikube
$response = Read-Host "Stop minikube? This will delete the cluster. (y/n)"
if ($response -eq 'y' -or $response -eq 'Y') {
    Write-Host "Stopping Minikube..."
    minikube stop
} else {
    Write-Host "Minikube will continue running."
}

Write-Host "Teardown complete!"
