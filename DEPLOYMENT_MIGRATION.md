# Deployment Migration Guide

## What Changed?

The deployment setup has been upgraded to support multiple environments (production and dev) with a single task definition template.

## Key Changes

### Before
- Single environment (production only)
- Task definition: `taskdef.json` with hardcoded values
- SSM parameters: `/vm-api/*`
- ECS service: `vm-api-svc`
- Manual deployment configuration for new environments

### After
- Multi-environment support (production + dev)
- Task definition template: `taskdef.template.json` with environment placeholders
- SSM parameters: `/vm-api-{env}/*` (e.g., `/vm-api-prod/*`, `/vm-api-dev/*`)
- ECS services: `vm-api-svc-prod` and `vm-api-svc-dev`
- Branch-based automatic deployments
- Single source of truth for environment variables

## Files Changed

### New Files
- `taskdef.template.json` - Parameterized task definition template
- `.github/workflows/deploy-dev.yml` - Dev environment deployment workflow
- `DEPLOYMENT_MIGRATION.md` - This document

### Modified Files
- `.github/workflows/deploy.yml` - Updated to use template and new service name
- `README.md` - Updated with new deployment documentation

### Deprecated Files
- `taskdef.json` - No longer used (can be deleted after successful migration)

## Migration Steps (One-Time)

These steps must be executed **once** to migrate from the old setup to the new setup:

### 1. Run Parameter Migration
```bash
cd ../vm-infra/scripts
./migrate-prod-params.sh
```
This renames `/vm-api/*` → `/vm-api-prod/*`

### 2. Run Service Rename
```bash
cd ../vm-infra/scripts
./rename-prod-service.sh
```
This renames `vm-api-svc` → `vm-api-svc-prod`

**⚠️ WARNING:** Brief downtime expected during service rename (typically < 1 minute)

### 3. Test Production Deployment
Push to main branch and verify:
```bash
# Check deployment
aws ecs describe-services --cluster vm-api-cluster-prod --services vm-api-svc-prod --region us-west-1

# Verify endpoint
curl https://api.vibemonitor.ai/health
```

### 4. Set Up Dev Environment (Optional)
Follow the complete guide: `../vm-infra/README_DEV_SETUP.md`

## Developer Workflow Changes

### Adding New Environment Variables

**Old way** (3 files):
1. `.env.example`
2. `app/core/config.py`
3. `taskdef.json`

**New way** (4 steps):
1. `.env.example`
2. `app/core/config.py`
3. `taskdef.template.json` (with `ENV_PLACEHOLDER`)
4. Add to SSM for each environment:
   ```bash
   aws ssm put-parameter --name '/vm-api-prod/var-name' --value 'prod-value' --type SecureString --region us-west-1
   aws ssm put-parameter --name '/vm-api-dev/var-name' --value 'dev-value' --type SecureString --region us-west-1
   ```

**Benefits:**
- Single template works for all environments
- No need to maintain multiple task definition files
- Clear separation of environment-specific values

### Deployment Workflow

**Before:**
- Only production deployments on `main` branch
- Manual setup for any new environments

**After:**
- `main` branch → Production (`api.vibemonitor.ai`)
- `dev` branch → Dev environment (`dev.vibemonitor.ai`)
- Automatic deployments on push
- Easy to add more environments (staging, qa, etc.)

## Rollback Plan

If issues arise during migration:

### Rollback SSM Parameters
```bash
# Production will still work with old parameters during transition
# Old parameters are preserved by migration script
```

### Rollback Service Name
The rename script preserves the old task definition, so you can:
1. Scale down new service: `aws ecs update-service --cluster vm-api-cluster-prod --service vm-api-svc-prod --desired-count 0 --region us-west-1`
2. Recreate old service name if needed (contact infrastructure team)

## Verification Checklist

After migration, verify:

- [ ] Production endpoint responds: `curl https://api.vibemonitor.ai/health`
- [ ] GitHub Actions workflow runs successfully on push to `main`
- [ ] Service name is `vm-api-svc-prod`: `aws ecs list-services --cluster vm-api-cluster-prod --region us-west-1`
- [ ] SSM parameters exist: `aws ssm get-parameters-by-path --path '/vm-api-prod' --region us-west-1`
- [ ] Task definition uses template: Check GitHub Actions logs for "Rendered task definition"

## Support

If you encounter issues:
1. Check GitHub Actions logs
2. Check ECS service events: `aws ecs describe-services --cluster vm-api-cluster-prod --services vm-api-svc-prod --region us-west-1`
3. Check CloudWatch logs: `aws logs tail /ecs/vm-api-logs-prod --follow --region us-west-1`
4. Contact the infrastructure team

## Benefits Summary

✅ **Single source of truth** - One task definition template for all environments
✅ **Easy environment setup** - Scripts handle infrastructure creation
✅ **Branch-based deployments** - Push to deploy automatically
✅ **Clear separation** - Production and dev are completely isolated
✅ **Consistent naming** - All resources follow `-prod` / `-dev` pattern
✅ **No duplicate configs** - Add environment variables once, use everywhere
✅ **Scalable** - Easy to add staging, QA, or other environments

## Timeline

- **Phase 1**: Migrate production (run migration scripts) ← **START HERE**
- **Phase 2**: Set up dev environment (optional, follow README_DEV_SETUP.md)
- **Phase 3**: Add more environments as needed (staging, qa, etc.)
