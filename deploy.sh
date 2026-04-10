#!/usr/bin/env bash
# First-time deployment script for EC2 (Ubuntu 22.04)
# Run as: bash deploy.sh
set -e

echo "=== Installing Docker ==="
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-plugin mysql-client
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER

echo "=== Installing MySQL client (for DB import) ==="
sudo apt-get install -y mysql-client

echo ""
echo "=== Done. Next steps ==="
echo ""
echo "1. Copy your .env file to this server:"
echo "   scp .env ubuntu@<EC2_IP>:~/claim_reprodue_agent/.env"
echo ""
echo "2. Add MYSQL_ROOT_PASSWORD to .env:"
echo "   echo 'MYSQL_ROOT_PASSWORD=choose_a_strong_password' >> .env"
echo ""
echo "3. Start all services:"
echo "   docker compose up -d"
echo ""
echo "4. Import ImmPort database (one-time, run from your local machine):"
echo "   mysqldump -u root immport_dr62 | gzip > immport_dr62.sql.gz"
echo "   scp immport_dr62.sql.gz ubuntu@<EC2_IP>:~/"
echo "   ssh ubuntu@<EC2_IP>"
echo "   zcat immport_dr62.sql.gz | docker exec -i claimrepro_mysql mysql -u root -p\$MYSQL_ROOT_PASSWORD immport_dr62"
echo ""
echo "5. Open port 80 in your EC2 security group, then visit http://<EC2_IP>"
