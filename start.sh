#!/bin/bash

# Start webhook server in the background
echo "🚀 Starting Webhook Server on port $PORT..."
python webhook_server.py &
WEBHOOK_PID=$!


# Trap signals and forward them to children
trap "kill $WEBHOOK_PID; exit" SIGINT SIGTERM

# Wait for webhook process
wait $WEBHOOK_PID
