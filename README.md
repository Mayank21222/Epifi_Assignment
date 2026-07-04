# Uptime Monitor

A lightweight, full-stack uptime monitor that periodically pings URLs and displays their operational status and response times.

## 1-Line Setup

```bash
docker compose up
```

- **Frontend Dashboard**: http://localhost:8080
- **Backend API**: http://localhost:5001

## Repository

- GitHub: https://github.com/Mayank21222/Epifi_Assignment

> **macOS note**: This project defaults to `HOST_PORT=5001` because macOS often reserves port 5000 for AirPlay Receiver. If you want to bind the backend to port 5000 instead, run:
>
> ```bash
> HOST_PORT=5000 docker compose up
> ```
> 
> Then use http://localhost:5000 for API calls.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Frontend    │────▶│  Backend API  │────▶│  SQLite DB    │
│  (nginx)     │     │  (Flask)     │     │  (/data/)     │
│  :8080       │◀────│  :5000       │     └──────────────┘
└─────────────┘     │  APScheduler  │
                     │  (pings URLs  │
                     │   every 60s)  │
                     └──────────────┘
```

## Testing Steps

### Verify "Up" state
1. Open the dashboard at http://localhost:8080
2. In the "Add URL to Monitor" form, enter: `https://example.com`
3. Click **Monitor**
4. Wait ~10 seconds and refresh (the page auto-polls every 5s)
5. The card should show a **green "Up"** badge with a response time (e.g. `120 ms`)

### Verify "Down" state
1. In the same form, enter: `https://thissitedoesnotexist.xyz`
2. Click **Monitor**
3. Wait ~10 seconds
4. The card should show a **red "Down"** badge with an error message like `Connection refused`

### Verify removal
1. Click the **Remove** button on any card
2. The card disappears from the dashboard

### Verify a local URL that is down
Use any private IP that isn't serving HTTP:
```
http://10.255.255.1:9999
```
This should also show a "Down" state with `Connection refused` or `Timeout`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/urls` | List all monitored URLs with latest check |
| POST | `/api/urls` | Register a URL (`{"url": "...", "name": "..."}`) |
| DELETE | `/api/urls/<id>` | Remove a monitored URL |
| GET | `/api/urls/<id>/checks` | Health check history (max 50) |
| GET | `/api/health` | Backend health check |

## Deployment Sketch (AWS ECS with Terraform)

Below is a minimal Terraform configuration that would deploy this application to AWS ECS Fargate.

```hcl
provider "aws" {
  region = "us-east-1"
}

resource "aws_ecs_cluster" "uptimer" {
  name = "uptimer-cluster"
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "uptimer-backend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([
    {
      name  = "backend"
      image = "your-registry/uptimer-backend:latest"
      portMappings = [{ containerPort = 5000 }]
      environment = [{ name = "DATABASE_PATH", value = "/data/uptimer.db" }]
      mountPoints = [{
        sourceVolume  = "data"
        containerPath = "/data"
      }]
    }
  ])

  volume {
    name = "data"
    efs_volume_configuration {
      file_system_id = aws_efs_file_system.uptimer.id
    }
  }
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "uptimer-frontend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([
    {
      name  = "frontend"
      image = "your-registry/uptimer-frontend:latest"
      portMappings = [{ containerPort = 80 }]
      environment = [
        { name = "API_BASE", value = "http://backend.uptimer.local:5000/api" }
      ]
    }
  ])
}

# ALB to route traffic
resource "aws_lb" "uptimer" {
  name               = "uptimer-alb"
  internal           = false
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "frontend" {
  port        = 80
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
}

resource "aws_lb_listener" "frontend_http" {
  load_balancer_arn = aws_lb.uptimer.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# EFS for persistent SQLite data
resource "aws_efs_file_system" "uptimer" {
  creation_token = "uptimer-data"
}

# IAM roles, VPC, subnets, and ECS service definitions omitted for brevity
# but would follow standard Fargate patterns.
```

**Key architectural decisions in this sketch:**

- **AWS ECS Fargate** — No servers to manage; scales down to zero
- **EFS** — Shared filesystem for SQLite persistence (across AZs). For higher throughput, swap to RDS or DynamoDB
- **ALB** — Single endpoint; route `/api/*` to backend, everything else to frontend
- **Service Discovery** — Frontend can resolve `backend.uptimer.local` via Cloud Map or hardcode the ALB DNS for simplicity
- **CI/CD** — Push images to ECR; Terraform updates ECS service with new task definition
