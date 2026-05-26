  #!/bin/bash
  set -a                                                                                        
  source /opt/app/apps/api/.env
  set +a                                                                                        
  exec /opt/app/apps/api/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
  SCRIPT
  cp /tmp/start.sh /opt/app/apps/api/start.sh                                                   
  chmod +x /opt/app/apps/api/start.sh     
  pm2 delete 1                                                                                  
  pm2 start /opt/app/apps/api/start.sh --name api --cwd /opt/app/apps/api                       
  pm2 save                  
