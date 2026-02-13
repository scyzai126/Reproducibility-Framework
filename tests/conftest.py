import os

# Set dummy env vars before any app imports that trigger config loading
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
os.environ.setdefault("MYSQL_URL", "mysql+aiomysql://user:pass@localhost:3306/testdb")
