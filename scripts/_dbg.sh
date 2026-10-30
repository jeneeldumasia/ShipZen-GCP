P="$1"; C=shipzen-cluster
for f in "name~'^pvc-'" \
  "labels.goog-k8s-cluster-name=$C" \
  "labels.goog-gke-volume:*" \
  "labels.goog-gke-volume=''" \
  "-labels.goog-gke-volume:NOSUCH AND labels.goog-gke-volume:''" \
  "description~'kubernetes.io/created-for/pvc'" \
  "description:kubernetes.io/created-for/pvc" \
  "description~'created-for'" \
  "users:*" "-users:*" \
  "labels.reclaim-policy-gke-io=retain" "-labels.reclaim-policy-gke-io=retain"; do
  n=$(gcloud compute disks list --project "$P" --filter="$f" --format='value(name)' 2>&1 | grep -c pvc-)
  echo "$n  <= $f"
done
gcloud compute disks list --project "$P" --filter="name~'^pvc-'" --format=json 2>&1 | python3 -c "import json,sys;d=json.load(sys.stdin)[0];print('labels:',d.get('labels'));print('desc:',d.get('description'));print('users:',d.get('users'))"
