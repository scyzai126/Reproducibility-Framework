# Infrastructure Layout

Use this directory for Infrastructure as Code.

Recommended structure:
- `infra/cdk/` or `infra/terraform/` for AWS resources.
- `infra/env/dev`, `infra/env/staging`, `infra/env/prod` for environment-specific settings.

Target AWS services:
- API: ECS Fargate + ALB
- Web: Amplify or ECS Fargate
- DB: RDS MySQL
- File storage: S3
- Secrets: AWS Secrets Manager / SSM Parameter Store
