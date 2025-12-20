# StoryForge AI - Production Deployment Guide

This guide covers deploying the StoryForge AI video editor to production using Railway (backend) and Vercel (frontend).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         USERS                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Vercel (Frontend)                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Next.js 15 + Auth.js v5                   │    │
│  │  • Dashboard UI                                      │    │
│  │  • Stripe Billing Portal                            │    │
│  │  • Job Management                                   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Railway (Backend)                          │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │   FastAPI API    │  │   Celery Worker  │                 │
│  │  • Video Upload  │  │  • Video Process │                 │
│  │  • Job Queue     │  │  • AI Generation │                 │
│  └──────────────────┘  └──────────────────┘                 │
│           │                    │                             │
│           ▼                    ▼                             │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │      Redis       │  │      MinIO       │                 │
│  │  (Job Queue)     │  │  (Video Storage) │                 │
│  └──────────────────┘  └──────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   External Services                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Neon DB     │  │ Memories.ai  │  │  ElevenLabs  │       │
│  │  (Postgres)  │  │  (Vision AI) │  │  (TTS)       │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Accounts Required:**
   - [Railway](https://railway.app) - Backend hosting
   - [Vercel](https://vercel.com) - Frontend hosting
   - [Neon](https://neon.tech) - PostgreSQL database
   - [Stripe](https://stripe.com) - Payment processing
   - [Memories.ai](https://memories.ai) - Vision AI
   - [ElevenLabs](https://elevenlabs.io) - Text-to-speech

2. **Domain:** (Optional but recommended)
   - Custom domain for frontend (e.g., `app.storyforge.ai`)
   - Custom domain for API (e.g., `api.storyforge.ai`)

---

## Step 1: Set Up Neon Database

1. Go to [Neon Console](https://console.neon.tech)
2. Create a new project
3. Copy the connection string (looks like `postgres://user:pass@host/db?sslmode=require`)
4. Save this as `DATABASE_URL`

---

## Step 2: Deploy Backend to Railway

### 2.1 Create Railway Project

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your repository
4. Choose the `backend` directory as the root

### 2.2 Add Redis Service

1. In your Railway project, click "New" → "Database" → "Redis"
2. Railway will automatically set `REDIS_URL` environment variable

### 2.3 Add MinIO Service (or use S3)

**Option A: MinIO on Railway**
1. Click "New" → "Docker Image"
2. Use image: `minio/minio`
3. Set command: `server /data --console-address ":9001"`
4. Add environment variables:
   - `MINIO_ROOT_USER`: your-access-key
   - `MINIO_ROOT_PASSWORD`: your-secret-key

**Option B: AWS S3**
1. Create an S3 bucket in AWS
2. Create IAM credentials with S3 access
3. Set environment variables accordingly

### 2.4 Configure Environment Variables

In Railway, add these environment variables:

```env
# Redis (auto-set by Railway)
REDIS_URL=redis://...

# MinIO/S3
MINIO_ENDPOINT=your-minio-host:9000
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key
MINIO_BUCKET_VIDEOS=videos
MINIO_BUCKET_OUTPUT=output
MINIO_SECURE=true

# AI Services
MEMORIES_API_KEY=your-memories-api-key
ELEVENLABS_API_KEY=your-elevenlabs-api-key
ELEVENLABS_VOICE_ID=your-voice-id

# Authentication
AUTH_SECRET=your-auth-secret-same-as-frontend
JWT_SECRET=your-jwt-secret

# CORS
CORS_ORIGINS=https://your-frontend-domain.vercel.app

# Webhook
WEBHOOK_SECRET=your-webhook-secret
```

### 2.5 Deploy Worker Service

1. In Railway, add another service from the same repo
2. Set root directory to `backend`
3. Override start command: `python -m celery -A app.workers.pipeline worker --loglevel=info`
4. Copy the same environment variables

---

## Step 3: Deploy Frontend to Vercel

### 3.1 Import Project

1. Go to [Vercel Dashboard](https://vercel.com/dashboard)
2. Click "Add New" → "Project"
3. Import your GitHub repository
4. Set root directory to `saas-frontend`

### 3.2 Configure Environment Variables

In Vercel project settings, add:

```env
# App
NEXT_PUBLIC_APP_URL=https://your-domain.vercel.app

# Backend API
NEXT_PUBLIC_API_URL=https://your-railway-backend.up.railway.app

# Database
DATABASE_URL=postgres://user:pass@host/db?sslmode=require

# Auth
AUTH_SECRET=your-auth-secret-generate-with-openssl

# OAuth (at least one required)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Email (Resend)
RESEND_API_KEY=your-resend-api-key
EMAIL_FROM=noreply@yourdomain.com

# Stripe
STRIPE_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
NEXT_PUBLIC_STRIPE_PRO_MONTHLY_PLAN_ID=price_...
NEXT_PUBLIC_STRIPE_PRO_YEARLY_PLAN_ID=price_...
NEXT_PUBLIC_STRIPE_BUSINESS_MONTHLY_PLAN_ID=price_...
NEXT_PUBLIC_STRIPE_BUSINESS_YEARLY_PLAN_ID=price_...

# Webhook
WEBHOOK_SECRET=your-webhook-secret
```

### 3.3 Run Database Migrations

After first deployment:

```bash
# In Vercel, add a build command or run locally:
npx prisma migrate deploy
```

---

## Step 4: Configure Stripe

### 4.1 Create Products

In [Stripe Dashboard](https://dashboard.stripe.com/products):

1. Create "Pro" product:
   - Monthly price: $29/month
   - Yearly price: $290/year
   - Copy price IDs

2. Create "Business" product:
   - Monthly price: $99/month
   - Yearly price: $990/year
   - Copy price IDs

### 4.2 Set Up Webhooks

1. Go to Developers → Webhooks
2. Add endpoint: `https://your-domain.vercel.app/api/webhooks/stripe`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
4. Copy webhook signing secret

---

## Step 5: Configure OAuth (Google)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing
3. Enable Google+ API
4. Go to Credentials → Create Credentials → OAuth 2.0 Client ID
5. Set authorized redirect URI: `https://your-domain.vercel.app/api/auth/callback/google`
6. Copy Client ID and Client Secret

---

## Step 6: Post-Deployment Checklist

- [ ] Verify frontend loads at your domain
- [ ] Test user registration/login
- [ ] Verify backend health check: `https://api.your-domain/health`
- [ ] Test video upload flow
- [ ] Verify Stripe checkout works
- [ ] Check webhook delivery in Stripe dashboard
- [ ] Monitor error logs in Railway and Vercel

---

## Environment Variables Summary

### Frontend (Vercel)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_APP_URL` | Frontend URL |
| `NEXT_PUBLIC_API_URL` | Backend API URL |
| `DATABASE_URL` | Neon Postgres connection string |
| `AUTH_SECRET` | NextAuth secret (generate with `openssl rand -base64 32`) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `RESEND_API_KEY` | Resend email API key |
| `EMAIL_FROM` | Sender email address |
| `STRIPE_API_KEY` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `NEXT_PUBLIC_STRIPE_*` | Stripe price IDs |

### Backend (Railway)

| Variable | Description |
|----------|-------------|
| `REDIS_URL` | Redis connection URL |
| `MINIO_ENDPOINT` | MinIO/S3 endpoint |
| `MINIO_ACCESS_KEY` | MinIO/S3 access key |
| `MINIO_SECRET_KEY` | MinIO/S3 secret key |
| `MEMORIES_API_KEY` | Memories.ai API key |
| `ELEVENLABS_API_KEY` | ElevenLabs API key |
| `AUTH_SECRET` | Same as frontend |
| `CORS_ORIGINS` | Frontend URL for CORS |

---

## Troubleshooting

### Frontend Issues

**Build fails with Prisma error:**
```bash
# Add to build command in Vercel:
prisma generate && next build
```

**Auth not working:**
- Verify `AUTH_SECRET` is set and matches
- Check OAuth redirect URIs are correct

### Backend Issues

**Worker not processing jobs:**
- Check Redis connection
- Verify worker service is running
- Check logs for errors

**Video upload fails:**
- Verify MinIO/S3 credentials
- Check bucket permissions
- Ensure CORS is configured on storage

### Database Issues

**Migrations fail:**
```bash
# Reset and re-run migrations:
npx prisma migrate reset
npx prisma migrate deploy
```

---

## Scaling Considerations

1. **Backend Workers:** Increase Railway replicas for more processing capacity
2. **Database:** Upgrade Neon plan for more connections
3. **Storage:** Use S3 with CloudFront for better video delivery
4. **Redis:** Consider Redis cluster for high availability

---

## Security Checklist

- [ ] All secrets are in environment variables, not code
- [ ] CORS is restricted to your frontend domain
- [ ] Webhook secrets are verified
- [ ] Rate limiting is enabled
- [ ] HTTPS is enforced everywhere
- [ ] Database connections use SSL

