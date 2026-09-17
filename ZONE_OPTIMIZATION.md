# Single Zone Optimization for Development

## Changes Made

Reduced GKE cluster from **3 zones to 1 zone** for development to save costs.

### Before (3 zones)
```
zones: us-central1-a, us-central1-b, us-central1-c
nodes: 1 per zone = 3 total
machine: n2-standard-4
cost: ~$363/month
```

### After (1 zone)
```
zones: us-central1-a only
nodes: 1 total
machine: n2-standard-4 (same performance)
cost: ~$121/month
```

## Cost Savings

**$242/month saved (67% reduction)** 💰

- Monthly: $363 → $121 = **$242 saved**
- Yearly: $4,356 → $1,452 = **$2,904 saved**

## What Changed in `terraform/main.tf`

1. **Cluster zones:**
   ```diff
   - node_locations = ["us-central1-a", "us-central1-b", "us-central1-c"]
   + node_locations = ["us-central1-a"]  # Single zone for dev
   ```

2. **Node pool:**
   ```diff
   - node_count = 1  # Per zone, so 3 total
   + node_count = 1  # Single zone, 1 node total for dev
   
   - min_node_count = 1  # Per zone
   + min_node_count = 1  # Single zone
   
   - max_node_count = 3  # Per zone, max 9 nodes total
   + max_node_count = 3  # Single zone, max 3 nodes total for burst
   ```

## Trade-offs

### What You Keep ✅
- Same performance (n2-standard-4 per node)
- Same resources available (4 vCPU, 16 GB RAM)
- Can still autoscale up to 3 nodes if needed
- Plenty for dev/test workloads

### What You Lose ❌
- No automatic failover between zones
- If us-central1-a has issues, cluster goes down
- Can't test multi-zone HA scenarios

**For development: This is totally fine!** ✅

## Deployment Instructions

**IMPORTANT:** Wait for current deployment to complete first!

### After Current Deployment Finishes:

1. **Commit the changes:**
   ```powershell
   git add terraform/main.tf ZONE_OPTIMIZATION.md
   git commit -m "cost: reduce to single zone for dev (save $242/month)"
   ```

2. **Push to trigger rebuild:**
   ```powershell
   git push origin main
   ```

3. **GitHub Actions will automatically:**
   - Destroy the 3-zone cluster
   - Create new 1-zone cluster
   - Deploy all services
   - Takes ~20-25 minutes

4. **Verify after deployment:**
   ```powershell
   gcloud container clusters describe shipzen-cluster --region us-central1 --format="get(locations)"
   # Should show: us-central1-a only
   
   kubectl get nodes
   # Should show: 1 node
   ```

## For Production Later

When you're ready to go to production, revert to multi-zone:

```diff
- node_locations = ["us-central1-a"]
+ node_locations = ["us-central1-a", "us-central1-b", "us-central1-c"]

- node_count = 1  # Single zone
+ node_count = 1  # Per zone, 3 total
```

This gives you high availability and automatic zone failover.

## Summary

- **Dev:** 1 zone, $121/month ← **Use this now**
- **Prod:** 3 zones, $363/month ← Switch to this later

You're saving **$242/month** during development while keeping the same performance! 🎉
