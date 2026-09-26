import kubernetes
from kubernetes import client, config
import ast

config.load_kube_config()
v1 = client.CoreV1Api()
pods = v1.list_namespaced_pod('default', label_selector='job-name=nixpacks-shipzen-job2')
pod_name = pods.items[0].metadata.name
log = v1.read_namespaced_pod_log(name=pod_name, namespace='default', follow=False, _preload_content=True)

if isinstance(log, str) and log.startswith("b'") and log.endswith("'"):
    try:
        log_bytes = ast.literal_eval(log)
        if isinstance(log_bytes, bytes):
            log_str = log_bytes.decode('utf-8', errors='replace')
            print("DECODED PROPERLY:")
            print(log_str)
    except Exception as e:
        print("EVAL FAILED:", e)
else:
    print("NOT A BYTE REP STRING")
