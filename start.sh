#!/bin/bash

# Start webhook server in the background
echo "🚀 Starting Webhook Server on port $PORT..."
python webhook_server.py &
WEBHOOK_PID=$!

# Start hunter engine in the background
echo "🎯 Starting Hunter Engine..."
python hunter_engine.py &
HUNTER_PID=$!

# Trap signals and forward them to children
trap "kill $WEBHOOK_PID $HUNTER_PID; exit" SIGINT SIGTERM

# Wait for both processes
wait $WEBHOOK_PID $HUNTER_PID
