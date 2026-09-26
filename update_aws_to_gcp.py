import os
from pathlib import Path

docs_dir = Path("c:/Project/ShipZen-GCP/docs")
scripts = [Path("c:/Project/ShipZen-GCP/generate_docs.py")]

replacements = {
    "AWS": "GCP",
    "EKS": "GKE",
    "ECR": "GAR",
    "S3": "GCS",
    "Secrets Manager": "Secret Manager",
    "IRSA": "Workload Identity",
    "AWS Secrets Manager": "GCP Secret Manager",
    "AWS_SM": "GCP_SM",
    "AWS_ALB": "GCP_LB"
}

def replace_in_file(file_path):
    try:
        content = file_path.read_text(encoding='utf-8')
        new_content = content
        
        # specific fix for AWS Secrets Manager since Secrets Manager might overlap
        new_content = new_content.replace("AWS Secrets Manager", "GCP Secret Manager")
        
        for k, v in replacements.items():
            if k == "AWS Secrets Manager": continue # already handled
            new_content = new_content.replace(k, v)
            
        if new_content != content:
            file_path.write_text(new_content, encoding='utf-8')
            print(f"Updated {file_path}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

for md_file in docs_dir.rglob("*.md"):
    replace_in_file(md_file)

for script in scripts:
    replace_in_file(script)

print("Done updating AWS terms to GCP.")
