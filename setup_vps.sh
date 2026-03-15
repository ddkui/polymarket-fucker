#!/bin/bash

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt-get install -y docker-compose-plugin

# Create directory for the bot
mkdir -p ~/btc-polymarket-bot
cd ~/btc-polymarket-bot

echo "VPS Setup Complete!"
echo "Next steps:"
echo "1. Upload your files to ~/btc-polymarket-bot"
echo "2. Edit your .env file"
echo "3. Run: docker compose up -d"
