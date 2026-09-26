from pg8000.native import Connection
import os
from dotenv import load_dotenv
load_dotenv('.secrets.env')
conn = Connection(user='postgres', password=os.getenv('PG_PASSWORD'), host='localhost', database='shipzen')
for row in conn.run('SELECT deployment_id, state, updated_at, error_message FROM deployments ORDER BY updated_at DESC LIMIT 5;'):
    print(row)
