# Vercel + Render Deployment Guide

## Overview
Deploy your Arogya-AI application with:
- **Frontend**: Vercel (Next.js optimized, automatic HTTPS, global CDN)
- **Backend**: Render (Python/FastAPI, WebSocket support, reliable hosting)

---

## 🎯 Required Files (Already Created)

### Backend (Render)
- ✅ `render.yaml` - Render service configuration
- ✅ `backend/render_main.py` - Render entry point
- ✅ `backend/requirements.txt` - Python dependencies
- ✅ `backend/app/main.py` - FastAPI app with production CORS

### Frontend (Vercel)
- ✅ `frontend/vercel.json` - Vercel configuration
- ✅ `frontend/lib/config.ts` - Production config helper
- ✅ `frontend/package.json` - Node.js dependencies
- ✅ `frontend/next.config.js` - Next.js configuration

---

## 🚀 Step 1: Deploy Backend to Render

### 1.1 Create Render Account
1. Go to [render.com](https://render.com)
2. Sign up with GitHub
3. Click "New +" → "Web Service"

### 1.2 Connect Repository
1. Connect your GitHub repository
2. Select your repository from the list
3. Configure deployment settings:

```
Name: arogya-ai-backend
Runtime: Python 3
Region: Oregon (US West) or closest to your users
Branch: main
Root Directory: backend
Build Command: pip install -r requirements.txt
Start Command: python render_main.py
```

### 1.3 Set Environment Variables
In Render dashboard, add these environment variables:

```env
# Required - Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key

# Required - Google Cloud (for STT/Translation)
GOOGLE_CREDENTIALS_JSON={"type":"service_account","project_id":"your-project",...}

# Optional - OpenAI (for Whisper fallback)
OPENAI_API_KEY=sk-...

# Will be set after frontend deployment
FRONTEND_URL=https://your-app.vercel.app
```

### 1.4 Deploy Backend
1. Click "Create Web Service"
2. Wait for deployment to complete
3. Note your Render URL: `https://your-app.onrender.com`

### 1.5 Test Backend
- Health check: `https://your-app.onrender.com/health`
- API docs: `https://your-app.onrender.com/docs`

---

## 🌐 Step 2: Deploy Frontend to Vercel

### 2.1 Create Vercel Account
1. Go to [vercel.com](https://vercel.com)
2. Sign up with GitHub
3. Click "New Project"

### 2.2 Import Repository
1. Import your GitHub repository
2. Configure project settings:

```
Framework Preset: Next.js
Root Directory: frontend
Build Command: npm run build
Output Directory: .next
Install Command: npm install
```

### 2.3 Set Environment Variables
In Vercel dashboard, add these environment variables:

```env
# Required - Backend URL (use your Render URL)
NEXT_PUBLIC_BACKEND_URL=https://your-app.onrender.com

# Required - Database (frontend access)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key

# Optional - Analytics
NEXT_PUBLIC_GA_ID=G-XXXXXXXXXX
```

### 2.4 Deploy Frontend
1. Click "Deploy"
2. Wait for deployment to complete
3. Note your Vercel URL: `https://your-app.vercel.app`

---

## 🔗 Step 3: Connect Frontend and Backend

### 3.1 Update Backend CORS
1. Go back to Render dashboard
2. Add environment variable:
   ```env
   FRONTEND_URL=https://your-app.vercel.app
   ```
3. Redeploy backend to update CORS settings

### 3.2 Test Integration
1. Open your Vercel URL: `https://your-app.vercel.app`
2. Check browser console for any CORS errors
3. Test API calls are reaching backend
4. Verify WebSocket connections work

---

## ✅ Testing Checklist

### Backend Testing (Render)
- [ ] Health endpoint responds: `/health`
- [ ] API documentation loads: `/docs`
- [ ] WebSocket endpoint accessible: `/ws/captions/test/doctor`
- [ ] Database connection works
- [ ] Google Cloud STT configured (check logs)
- [ ] CORS allows your Vercel domain

### Frontend Testing (Vercel)
- [ ] **CRITICAL**: Open in new tab (not preview) for HTTPS
- [ ] Frontend loads without errors
- [ ] API calls reach backend successfully
- [ ] Camera/microphone permissions work
- [ ] WebSocket connections establish
- [ ] Video calls work end-to-end
- [ ] Live captions transcribe speech

### Integration Testing
- [ ] User registration/login works
- [ ] Video call room loads
- [ ] Live captions connect and display
- [ ] Database operations succeed
- [ ] No CORS errors in browser console

---

## 🎬 Video Call Requirements

### HTTPS (Automatic)
- ✅ Vercel provides automatic HTTPS
- ✅ Render provides automatic HTTPS
- ✅ WebRTC requires HTTPS for camera/microphone

### Browser Permissions
- Camera access required
- Microphone access required
- **Always use "Open in new tab"** for video features

### WebSocket Support
- ✅ Render supports WebSocket connections
- ✅ Vercel supports WebSocket client connections
- ✅ Live captions use WSS (secure WebSocket)

---

## 🔍 Troubleshooting

### Common Issues

#### 1. CORS Errors
```
Access to fetch at 'render-url' from origin 'vercel-url' has been blocked by CORS policy
```
**Solution**: 
- Add `FRONTEND_URL=https://your-app.vercel.app` to Render environment
- Redeploy backend

#### 2. WebSocket Connection Failed
```
WebSocket connection to 'wss://your-app.onrender.com/ws/captions' failed
```
**Solution**:
- Check backend is running (not sleeping)
- Verify WebSocket URL uses `wss://` (secure)
- Check Render logs for errors

#### 3. Camera/Microphone Not Working
```
NotAllowedError: Permission denied
```
**Solution**:
- Ensure using HTTPS (both platforms provide this)
- Click "Open in new tab" (not Vercel preview)
- Grant permissions in browser settings

#### 4. Backend Sleeping (Render Free Tier)
```
Service unavailable (503)
```
**Solution**:
- Render free tier sleeps after 15 minutes of inactivity
- First request will wake it up (may take 30-60 seconds)
- Consider upgrading to paid plan for production

---

## 📊 Monitoring

### Render Backend
- Check Render dashboard for logs
- Monitor service status
- Watch for sleep/wake cycles on free tier

### Vercel Frontend
- Check Vercel dashboard for build logs
- Monitor Core Web Vitals
- Watch for runtime errors

### Database (Supabase)
- Monitor API usage in Supabase dashboard
- Check connection logs
- Watch for quota limits

---

## 🎯 Production URLs

After successful deployment:

- **Frontend**: `https://your-app.vercel.app`
- **Backend**: `https://your-app.onrender.com`
- **API Docs**: `https://your-app.onrender.com/docs`
- **Health Check**: `https://your-app.onrender.com/health`

---

## 💰 Cost Breakdown

### Render (Backend)
- **Free Tier**: 750 hours/month
- **Paid**: $7/month for always-on service
- **Includes**: WebSocket, HTTPS, custom domains

### Vercel (Frontend)
- **Free Tier**: 100GB bandwidth, unlimited deployments
- **Paid**: $20/month for team features
- **Includes**: Global CDN, automatic HTTPS, preview deployments

### Total Cost
- **Free**: $0/month (with limitations)
- **Production**: ~$27/month for both platforms

---

## 🏆 Success Criteria

Your deployment is successful when:

1. ✅ Frontend loads on Vercel with HTTPS
2. ✅ Backend responds on Render with HTTPS
3. ✅ API calls work between platforms
4. ✅ WebSocket connections establish
5. ✅ Video calls work with camera/microphone
6. ✅ Live captions transcribe in real-time
7. ✅ Database operations complete successfully
8. ✅ No CORS or connection errors

**Ready for production! 🎉**