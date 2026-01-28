# bound-fastapi

## Setup

```bash
# Install dependencies
uv sync

# Copy env file and fill in values
cp .env.example .env

# Install pre-commit hooks
uv run pre-commit install
```

## Development

```bash
# Run dev server (port 8000)
uv run fastapi dev app/main.py --port 8000

# Run with Docker (app + PostgreSQL)
docker compose up

# Rebuild and run
docker compose up --build

# Stop and remove volumes
docker compose down -v
```

## Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "description"

# Apply all migrations
uv run alembic upgrade head

# Rollback one migration
uv run alembic downgrade -1

# Show current migration
uv run alembic current

# Show migration history
uv run alembic history
```

## Linting & Formatting

```bash
# Lint
uv run ruff check .

# Lint and auto-fix
uv run ruff check --fix .

# Format
uv run ruff format .

# Check formatting without changes
uv run ruff format --check .
```

## Docker

```bash
# Build image
docker build -t bound-fastapi .

# Run container
docker run -p 8000:8000 bound-fastapi
```

## API Docs

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

## AWS Deployment

CloudFormation templates are in `aws/cloudformation/`. Deploy in this order:

```bash
# 1. VPC and networking
aws cloudformation deploy --template-file aws/cloudformation/vpc.yml --stack-name bound-vpc

# 2. S3 storage bucket
aws cloudformation deploy --template-file aws/cloudformation/s3.yml --stack-name bound-s3

# 3. ECS Fargate service (creates the ECS security group needed by RDS)
aws cloudformation deploy --template-file aws/cloudformation/ecs.yml --stack-name bound-ecs \
  --parameter-overrides ContainerImage=<your-ecr-image-uri> DBMasterPassword=<password> \
  --capabilities CAPABILITY_NAMED_IAM

# 4. RDS PostgreSQL
aws cloudformation deploy --template-file aws/cloudformation/rds.yml --stack-name bound-rds \
  --parameter-overrides DBMasterPassword=<password>
```

## Project Structure

```
app/
├── api/routes/    # Route handlers
├── core/          # Config and settings
├── db/            # Database session and base model
├── models/        # SQLAlchemy ORM models
├── schemas/       # Pydantic request/response schemas
└── services/      # Business logic (S3, etc.)
aws/cloudformation/ # AWS infrastructure templates
migrations/         # Alembic database migrations
tests/              # Test suite
```
