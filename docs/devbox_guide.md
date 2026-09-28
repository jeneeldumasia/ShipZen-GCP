# ShipZen DevBox Guide

The **ShipZen DevBox** is a persistent, highly secure VM running Debian 12 in your GCP project's `default` VPC. It is designed to let you safely run the Antigravity IDE / VS Code, manage your GKE cluster, build containers, and debug issues without triggering local security policies.

---

## 1. Connecting via SSH (IAP Tunnel)

The DevBox is secured behind Google Cloud's Identity-Aware Proxy (IAP). Ingress is completely blocked by firewall, and access is authenticated directly through your GCP IAM credentials.

Connect from your local terminal:

```powershell
gcloud compute ssh shipzen-devbox --zone=us-central1-a --tunnel-through-iap --project=project-ce3f7c39-eceb-4221-a76
```

---

## 2. Option A: Browser-Based IDE (`code-server`)

The DevBox comes with `code-server` installed, giving you a full VS Code interface directly inside any browser.

1. SSH into the DevBox:
   ```bash
   code-server --bind-addr 127.0.0.1:8080 --auth none
   ```
2. Open a separate terminal on your local machine and create an SSH tunnel:
   ```powershell
   gcloud compute ssh shipzen-devbox --zone=us-central1-a --tunnel-through-iap --project=project-ce3f7c39-eceb-4221-a76 --ssh-flag="-L 8080:localhost:8080"
   ```
3. Open your browser and navigate to:
   ```text
   http://localhost:8080
   ```

---

## 3. Option B: Remote Desktop (XRDP — XFCE4 / KDE Plasma)

### 3.1 First-Time Setup: Set User Password
GCP Linux instances do not have passwords enabled by default. Before connecting to XRDP for the first time, SSH into the DevBox and set a password:

```bash
# Check your username
whoami

# Set your password
sudo passwd $USER
```

### 3.2 Establish the RDP Tunnel
From your local Windows terminal, forward local port `3390` to remote port `3389` (port 3390 avoids conflicts with local Windows RDP):

```powershell
gcloud compute ssh shipzen-devbox --zone=us-central1-a --tunnel-through-iap --project=project-ce3f7c39-eceb-4221-a76 --ssh-flag="-L 3390:localhost:3389"
```

### 3.3 Connect with Remote Desktop
1. Open **Remote Desktop Connection** (`mstsc.exe`).
2. Computer: `localhost:3390`
3. Enter your username (from `whoami`, e.g. `jeneeld7492`) and the password you set.

---

## 4. Switching Desktop Environments (XFCE vs. KDE Plasma)

### Using KDE Plasma
If you install KDE Plasma (`sudo apt-get install -y kde-plasma-desktop`), configure your session properly to enable software rendering and D-Bus integration:

1. Configure `~/.xsession` for your user:
   ```bash
   cat << 'EOF' > ~/.xsession
   #!/bin/bash
   export XDG_CURRENT_DESKTOP=KDE
   export XDG_SESSION_DESKTOP=KDE
   export DESKTOP_SESSION=plasma
   export LIBGL_ALWAYS_SOFTWARE=1
   export QT_X11_NO_MITSHM=1

   # Launch KDE inside a D-Bus session
   exec dbus-run-session startplasma-x11
   EOF

   chmod +x ~/.xsession
   ```

2. Set KDE as the system-wide default:
   ```bash
   sudo update-alternatives --set x-session-manager /usr/bin/startplasma-x11
   ```

3. Restart XRDP:
   ```bash
   sudo systemctl restart xrdp
   ```

### Switching back to XFCE
```bash
echo "startxfce4" > ~/.xsession
sudo update-alternatives --set x-session-manager /usr/bin/startxfce4
sudo systemctl restart xrdp
```

---

## 5. Hardware & Resizing

The DevBox is running on a high-performance **`c2-standard-4`** instance (4 dedicated Compute-Optimized vCPUs, 16GB RAM). This tier provides dedicated physical CPU execution and ample memory for KDE Plasma, Docker, local builds, and multiple IDE instances without CPU throttling or memory swapping.

Changing the machine type in the future remains an **in-place hardware upgrade**. Your boot disk, code, logins, installed tools, and Docker images will **NOT** be deleted.

### To resize in the future via `gcloud`:
```bash
# 1. Stop the instance
gcloud compute instances stop shipzen-devbox --zone=us-central1-a

# 2. Resize machine type
gcloud compute instances set-machine-type shipzen-devbox --zone=us-central1-a --machine-type=<NEW_TYPE>

# 3. Start the instance
gcloud compute instances start shipzen-devbox --zone=us-central1-a
```

*Remember to update `machine_type = "e2-standard-4"` in [terraform-devbox/main.tf](file:///c:/Project/ShipZen-GCP/terraform-devbox/main.tf) to avoid configuration drift.*

---

## 6. Troubleshooting Common Issues

### XRDP Crashes Immediately After Password
1. **Stale X11 sockets**: Run:
   ```bash
   sudo rm -rf /tmp/.X11-unix/* /tmp/.X*-lock
   sudo systemctl restart xrdp
   ```
2. **Missing D-Bus or OpenGL Crash**: Ensure `LIBGL_ALWAYS_SOFTWARE=1` and `dbus-run-session` are set in `~/.xsession` (see Section 4).
3. **Out of Memory**: Check RAM with `free -h`. If memory is exhausted, restart heavy background containers or resize the instance.
4. **Inspect logs**:
   ```bash
   tail -n 50 ~/.xsession-errors
   sudo tail -n 50 /var/log/xrdp-sesman.log
   ```

---

## 7. Debugging the GKE Cluster

Since the DevBox is authenticated via its Service Account (`shipzen-devbox-sa`), it has container admin access to your cluster and Artifact Registry.

```bash
# Get cluster credentials
gcloud container clusters get-credentials shipzen-cluster --region us-central1 --project=project-ce3f7c39-eceb-4221-a76

# Inspect builder pods and logs
kubectl get pods -n shipzen-build
kubectl logs <pod-name> -n shipzen-build
```

---

## 8. Deletion Protection

The DevBox is protected by `deletion_protection = true` in Terraform. This ensures a `terraform destroy` targeting cluster resources will never accidentally wipe the DevBox.

If you intentionally want to decommission the DevBox, first set `deletion_protection = false` in `terraform-devbox/main.tf`, run `terraform apply`, and then proceed with destruction.

