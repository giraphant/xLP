# Deployment Guide

Quick deployment instructions for xLP Hedge Engine.

## Docker Deployment (Recommended)

### 1. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit with your settings
nano .env
```

**Required variables:**
```env
EXCHANGE_NAME=lighter
EXCHANGE_PRIVATE_KEY=your_lighter_private_key
JLP_AMOUNT=100
ALP_AMOUNT=0
```

### 2. Start Service

```bash
# From project root, create logs directory
cd /path/to/xLP
mkdir -p logs

# Start with docker-compose
cd deploy
docker-compose up -d

# View logs
docker-compose logs -f
```

### 3. Stop Service

```bash
cd deploy
docker-compose down
```

## Manual Deployment

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
# Create .env file
cp deploy/.env.example .env
nano .env
```

### 3. Run

```bash
# From project root
python src/main.py
```

## Files in This Directory

- **Dockerfile** - Container image definition
- **docker-compose.yml** - Service orchestration
- **.dockerignore** - Build exclusions
- **.env.example** - Environment template

## Notes

- All paths in `docker-compose.yml` are relative to project root
- Logs are stored in `../logs/` (project root)
- Configuration via `.env` file (12-factor app)
