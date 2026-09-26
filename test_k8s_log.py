import kubernetes
from kubernetes import client, config
config.load_kube_config()
v1 = client.CoreV1Api()
pods = v1.list_namespaced_pod('default', label_selector='job-name=nixpacks-shipzen-job2')
if not pods.items:
    print("Pod not found")
else:
    pod_name = pods.items[0].metadata.name
    try:
        log = v1.read_namespaced_pod_log(name=pod_name, namespace='default', follow=False, _preload_content=True)
        print('LOG:', log)
    except Exception as e:
        print('EXCEPTION:', repr(e))
