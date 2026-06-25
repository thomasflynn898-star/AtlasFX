#!/bin/zsh
cd ~/Desktop/AtlasFX
source venv/bin/activate
python3 -c "import uvicorn; uvicorn.run('dashboard.app:app', host='0.0.0.0', port=8420, log_level='warning')"
