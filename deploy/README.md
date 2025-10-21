# xLP Hedge Engine - Deployment Guide

This directory contains all deployment-related files for the xLP Hedge Engine.

## Quick Start (Docker)

### 1. Configure Environment

```bash
# Copy environment template
cp deploy/.env.example .env

# Edit .env with your settings
# Required variables:
#   - EXCHANGE_NAME (mock or lighter)
#   - EXCHANGE_PRIVATE_KEY (for lighter)
#   - JLP_AMOUNT (USD value)
#   - ALP_AMOUNT (USD value)
```

### 2. Launch

```bash
# From project root
docker-compose up -d

# View logs
docker-compose logs -f hedge-engine

# Stop
docker-compose down
```

## Direct Installation (Development)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy and edit environment file
cp deploy/.env.example .env
# Edit .env with your configuration
```

### 3. Run

```bash
# From project root
python src/main.py
```

## Files in This Directory

- **Dockerfile** - Container image definition
- **docker-compose.yml** - Orchestration configuration (at project root)
- **.dockerignore** - Build exclusions
- **.env.example** - Environment variable template

## Important Notes

- All paths in `docker-compose.yml` are relative to project root
- Logs are stored in `logs/` directory
- Configuration follows 12-factor app principles (environment-based)
- Docker is the recommended deployment method

## Health Monitoring

The Docker container includes a health check that monitors the main Python process:
- Check interval: 60s
- Timeout: 10s
- Retries: 3
- Start period: 30s

## Logs

Logs are automatically rotated:
- Max size: 10MB per file
- Max files: 3
- Format: JSON (for structured logging)
