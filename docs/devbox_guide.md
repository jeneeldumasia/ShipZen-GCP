# ShipZen DevBox Guide

The **ShipZen DevBox** is a persistent, highly secure `e2-medium` VM running Debian 12 in your GCP project's `default` VPC. It is designed to let you safely run the Antigravity IDE, manage your GKE cluster, and debug issues without triggering local security policies (like ESET).

## 1. Connecting to the DevBox

The DevBox has **no public IP address**. All connections are routed securely through Google's Identity-Aware Proxy (IAP). 

To connect, run this command from your local terminal:

```powershell
gcloud compute ssh shipzen-devbox --zone=us-central1-a --tunnel-through-iap --project=project-ce3f7c39-eceb-4221-a76
```

## 2. Option A: Using the Browser-Based IDE (code-server)

The DevBox comes with `code-server` installed, which gives you a full VS Code interface directly in your browser.

1. SSH into the DevBox using the command above.
2. Start the code-server:
   ```bash
   code-server --bind-addr 127.0.0.1:8080 --auth none
   ```
3. Open a **new, separate terminal** on your local machine and create a secure tunnel:
   ```powershell
   gcloud compute ssh shipzen-devbox --zone=us-central1-a --tunnel-through-iap --project=project-ce3f7c39-eceb-4221-a76 -- -L 8080:localhost:8080 -N
   ```
4. Open your web browser and go to `http://localhost:8080`.

## 3. Option B: Using Full Remote Desktop (XFCE4 + XRDP)

If you prefer a full graphical Linux desktop environment:

1. Open a local terminal and create an RDP tunnel:
   ```powershell
   gcloud compute ssh shipzen-devbox --zone=us-central1-a --tunnel-through-iap --project=project-ce3f7c39-eceb-4221-a76 -- -L 3389:localhost:3389 -N
   ```
2. Open **Microsoft Remote Desktop** (or any RDP client) on your computer.
3. Connect to `localhost:3389`.

## 4. Debugging the GKE Cluster

Since the DevBox is authenticated via its Service Account, it has full Admin access to your GKE cluster and Artifact Registry.

Once you are SSH'd into the DevBox (or using the terminal inside the browser IDE), you can run:

```bash
# Get cluster credentials
gcloud container clusters get-credentials shipzen-cluster --region us-central1 --project=project-ce3f7c39-eceb-4221-a76

# Check for failed builder pods
kubectl get pods -n shipzen-build

# View logs for a specific pod
kubectl logs <pod-name> -n shipzen-build
```

## 5. Deletion Protection

The DevBox is protected by `deletion_protection = true` in Terraform. This ensures that a `terraform destroy` run against your main infrastructure will never accidentally delete your DevBox.

If you intentionally want to delete the DevBox, you must temporarily set `deletion_protection = false` in `terraform-devbox/main.tf`, deploy that change, and then destroy the VM.
