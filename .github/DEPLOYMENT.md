# Deployment Documentation

This document describes the GitHub Actions workflows for deploying the bound-fastapi application to AWS ECS.

## Overview

The deployment pipeline consists of multiple workflows that work together to ensure safe and reliable deployments:

1. **CI** (`ci.yml`) - Continuous Integration
2. **Deploy** (`deploy.yml`) - Full deployment pipeline
3. **Migrate** (`migrate.yml`) - Manual database migrations
4. **Rollback** (`rollback.yml`) - Emergency rollback

## Workflows

### 1. CI Workflow (`ci.yml`)

**Trigger:** All pushes and pull requests

**Purpose:** Validate code quality before deployment

**Steps:**
- Checkout code
- Set up Python 3.12
- Install dependencies with uv
- Run linting (ruff)
- Run code formatting checks
- Run pytest tests

**Note:** This workflow must pass before any deployment can succeed.

---

### 2. Deploy Workflow (`deploy.yml`)

**Trigger:**
- Push to `main` branch (automatic)
- Manual trigger via GitHub Actions UI

**Purpose:** Full production deployment with migrations

**Architecture:**
```
┌─────────────┐
│    Build    │  Build Docker image, push to ECR
└──────┬──────┘
       │
       v
┌─────────────┐
│   Migrate   │  Run database migrations in ECS
└──────┬──────┘
       │
       v
┌─────────────┐
│   Deploy    │  Update ECS service with new image
└──────┬──────┘
       │
       v
┌─────────────┐
│   Notify    │  Report deployment status
└─────────────┘
```

**Jobs:**

#### Job 1: Build
- Builds Docker image
- Tags with commit SHA and `latest`
- Pushes to ECR: `145023110003.dkr.ecr.us-east-1.amazonaws.com/bound-fastapi`
- Outputs image tag for downstream jobs

#### Job 2: Migrate
- Retrieves current ECS task definition
- Gets VPC configuration (subnets, security groups)
- Runs `alembic upgrade head` as one-off ECS task
- Waits for migration task to complete
- Fails deployment if migration fails
- Outputs logs on failure

#### Job 3: Deploy
- Downloads current task definition
- Updates image tag to new version
- Registers new task definition with ECS
- Updates ECS service to use new task definition
- Waits for service to stabilize
- Verifies health endpoint

#### Job 4: Notify
- Reports deployment status (success/failure)
- Outputs relevant commit information

**Environment Variables:**
- `AWS_REGION`: us-east-1
- `ECR_REPOSITORY`: Full ECR repository URI
- `ECS_CLUSTER`: production-bound-cluster
- `ECS_SERVICE`: production-bound-service
- `CONTAINER_NAME`: bound-fastapi

**Secrets Required:**
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `ECR_REPOSITORY`
- `ECS_CLUSTER`
- `ECS_SERVICE`

---

### 3. Migrate Workflow (`migrate.yml`)

**Trigger:** Manual only (workflow_dispatch)

**Purpose:** Run database migrations independently of deployment

**Use Cases:**
- Emergency migration fixes
- Check migration status
- Rollback migrations
- View migration history

**Available Commands:**
1. `upgrade head` - Apply all pending migrations (default)
2. `downgrade -1` - Rollback last migration
3. `current` - Show current migration revision
4. `history` - Show migration history

**How to Use:**
1. Go to Actions > Run Database Migrations
2. Click "Run workflow"
3. Select migration command
4. Click "Run workflow"
5. Monitor logs for success/failure

**Steps:**
- Configure AWS credentials
- Get VPC configuration from running service
- Run migration command in ECS task
- Wait for completion
- Display logs
- Report status

---

### 4. Rollback Workflow (`rollback.yml`)

**Trigger:** Manual only (workflow_dispatch)

**Purpose:** Emergency rollback to previous version

**⚠️ Important Notes:**
- **DOES** rollback application code
- **DOES NOT** rollback database migrations
- Use when new deployment has critical bugs
- Manual DB migration rollback may be needed

**Options:**
- **Automatic:** Rollback to immediately previous revision (revision N-1)
- **Manual:** Specify exact task definition revision number

**How to Use:**

**Option 1: Automatic Rollback**
1. Go to Actions > Rollback Deployment
2. Click "Run workflow"
3. Leave revision field empty
4. Click "Run workflow"

**Option 2: Rollback to Specific Revision**
1. Find desired revision number:
   ```bash
   aws ecs list-task-definitions --family-prefix production-bound
   ```
2. Go to Actions > Rollback Deployment
3. Enter revision number (e.g., `42`)
4. Click "Run workflow"

**Steps:**
1. Get current task definition revision
2. Determine target revision (N-1 or specified)
3. Verify target task definition exists
4. Update ECS service to use target revision
5. Wait for service to stabilize
6. Verify rollback successful
7. Test health endpoint
8. Display post-rollback warnings

**Post-Rollback Actions:**
If database migrations are incompatible:
1. Run migration workflow with `downgrade -1`
2. Verify application functionality
3. Monitor logs and metrics

---

## Deployment Process

### Normal Deployment Flow

1. **Develop** - Make changes on feature branch
2. **Test Locally** - Run `uv run pytest`
3. **Create PR** - CI workflow runs automatically
4. **Review** - Code review and CI must pass
5. **Merge** - Merge to main branch
6. **Deploy** - Automatic deployment starts
   - Build Docker image
   - Run migrations
   - Deploy to ECS
   - Verify health

### Manual Migration

```bash
# If you need to run migrations separately:
1. Go to GitHub Actions
2. Select "Run Database Migrations"
3. Choose command (default: upgrade head)
4. Run workflow
```

### Emergency Rollback

```bash
# If deployment has critical issues:
1. Go to GitHub Actions
2. Select "Rollback Deployment"
3. Leave revision empty for automatic rollback
4. Run workflow
5. If needed, manually rollback migrations
```

---

## Monitoring Deployments

### Check Deployment Status

**Via GitHub Actions:**
- Go to Actions tab
- Click on latest workflow run
- View job details and logs

**Via AWS CLI:**
```bash
# Check service status
aws ecs describe-services \
  --cluster production-bound-cluster \
  --services production-bound-service

# Check task status
aws ecs list-tasks \
  --cluster production-bound-cluster \
  --service production-bound-service

# View logs
aws logs tail /ecs/production-bound --follow
```

**Via AWS Console:**
- Go to ECS > Clusters > production-bound-cluster
- Click on service > Deployments tab
- View tasks and logs

### Health Check

```bash
# Test health endpoint
curl https://bound.sh/health

# Or via ALB directly
curl http://production-bound-alb-505617971.us-east-1.elb.amazonaws.com/health
```

---

## Troubleshooting

### Deployment Failed

**1. Build Job Failed:**
- Check Docker build logs
- Verify Dockerfile syntax
- Check dependencies in pyproject.toml

**2. Migration Job Failed:**
- Check migration logs in GitHub Actions
- Verify database connectivity
- Check migration file syntax
- Use migrate workflow to check current state

**3. Deploy Job Failed:**
- Check ECS service events
- Verify task definition is valid
- Check security groups and networking
- Review CloudWatch logs

### Rollback Failed

**1. Task Definition Not Found:**
- Verify revision number is correct
- List available revisions:
  ```bash
  aws ecs list-task-definitions --family-prefix production-bound
  ```

**2. Service Won't Stabilize:**
- Check ECS service events
- Verify tasks are starting
- Check CloudWatch logs
- Verify security groups and networking

### Migration Issues

**1. Migration Failed:**
- Check database connectivity
- Verify migration syntax
- Check for conflicting migrations
- Review alembic history

**2. Need to Rollback Migration:**
- Use migrate workflow with `downgrade -1`
- Verify database state
- Re-run application deployment if needed

---

## Best Practices

### Before Deploying

1. ✅ All tests pass locally
2. ✅ Code reviewed and approved
3. ✅ Database migrations tested locally
4. ✅ No breaking changes without coordination
5. ✅ CI workflow passes on PR

### During Deployment

1. 📊 Monitor GitHub Actions logs
2. 📊 Watch ECS service in AWS Console
3. 📊 Check CloudWatch logs for errors
4. 📊 Test endpoints after deployment

### After Deployment

1. ✅ Verify health endpoint responds
2. ✅ Test critical user flows
3. ✅ Monitor error rates
4. ✅ Check application metrics
5. ✅ Review CloudWatch logs

### Migration Guidelines

1. **Always test migrations locally first**
   ```bash
   uv run alembic upgrade head
   uv run alembic downgrade -1
   ```

2. **Write reversible migrations**
   - Include both `upgrade()` and `downgrade()`
   - Test rollback path

3. **Avoid destructive changes**
   - Don't drop columns with data
   - Use multi-step migrations for breaking changes

4. **Coordinate with team**
   - Communicate schema changes
   - Plan downtime if needed

---

## GitHub Secrets

Required secrets for deployment:

| Secret | Description | Example |
|--------|-------------|---------|
| `AWS_ACCESS_KEY_ID` | IAM user access key | `AKIAXXXXXXXXXXXXXXXX` |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `AWS_REGION` | AWS region | `us-east-1` |
| `ECR_REPOSITORY` | ECR repository URI | `145023110003.dkr.ecr.us-east-1.amazonaws.com/bound-fastapi` |
| `ECS_CLUSTER` | ECS cluster name | `production-bound-cluster` |
| `ECS_SERVICE` | ECS service name | `production-bound-service` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `JWT_SECRET_KEY` | JWT signing key | `xxxxxxxxxxxxxxxx` |
| `RESEND_API_KEY` | Resend email API key | `re_xxxxxxxx` |
| `RESEND_FROM_EMAIL` | From email address | `noreply@bound.sh` |

---

## IAM Permissions

The `github-actions-deploy` IAM user has these permissions:

- **ECR:** Push/pull Docker images
- **ECS:** Update services, register task definitions, run tasks
- **IAM:** Pass roles to ECS tasks
- **CloudWatch Logs:** Create and write logs

---

## Support

For issues or questions:
1. Check CloudWatch logs
2. Review GitHub Actions logs
3. Check ECS service events
4. Review this documentation
5. Contact DevOps team
