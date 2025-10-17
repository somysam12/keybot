# 🚀 Render Deployment Guide

## Render pe Deploy Kaise Karein

### Step 1: Repository Setup
1. Apne GitHub repository ko update karo (latest code push karo)
2. Make sure `.env` file push **NA** ho (already gitignored hai)

### Step 2: Render Account Setup
1. [Render.com](https://render.com) pe jao
2. GitHub se sign up/login karo
3. "New +" button pe click karo
4. **"Web Service"** select karo

### Step 3: Configuration
1. **Repository:** Apna GitHub repo select karo
2. **Name:** `telegram-key-bot` (ya koi bhi naam)
3. **Region:** Singapore (ya nearest region)
4. **Branch:** `main`
5. **Runtime:** Python 3
6. **Build Command:** `pip install -r requirements.txt`
7. **Start Command:** `python verify_key_bot.py`

### Step 4: Environment Variables
Render dashboard mein **Environment** section mein ye add karo:

```
BOT_TOKEN=your_bot_token_here
ADMIN_ID=5952524867
```

⚠️ **Important Notes:**
- Environment variables ko Render dashboard se add karna hai, code mein nahi!
- `PORT` variable **add mat karo** - Render automatically provide karega!
- Bot khud se Render ka assigned port use kar lega

### Step 5: Deploy
1. "Create Web Service" button pe click karo
2. Build process start hoga (2-3 minutes)
3. Deploy successful hone pe bot live ho jayega! ✅

## 🔍 Health Check
- Render automatically health check karega assigned port pe
- Bot running hai ya nahi check karne ke liye: `https://your-app.onrender.com/`
- Response: "Bot is running ✅"
- **Note:** Render dynamically port assign karta hai, bot automatically use kar lega

## 📊 Monitoring
- **Logs:** Render dashboard > Logs tab
- **Metrics:** Auto-scale and performance monitoring
- **Auto-restart:** Agar crash ho to automatically restart hoga

## 🆓 Free Tier Notes
- Free tier mein service 15 minutes inactive hone pe sleep mode mein chali jayegi
- First request pe wapas wake up hogi (30 seconds lag ho sakta hai)
- Bot commands hamesha work karenge (Telegram polling active rahegi)

## 🔄 Updates Deploy Kaise Karein
1. Code changes karo
2. GitHub pe push karo: `git push origin main`
3. Render automatically detect karega aur re-deploy karega
4. Auto-deployment enabled hai!

## ⚡ Quick Deploy (Using render.yaml)
Repository mein `render.yaml` file already hai. Bas Render pe:
1. "New +" → "Blueprint"
2. Repository select karo
3. Environment variables add karo
4. Deploy!

## 🛠️ Troubleshooting
**Bot offline ho to:**
1. Render logs check karo
2. Environment variables verify karo
3. BOT_TOKEN valid hai check karo
4. Bot ko channels mein admin banaya hai check karo

**Build fail ho to:**
1. Requirements.txt check karo
2. Python version compatible hai check karo
3. Build logs mein error dekho

## ✅ Pre-Deployment Checklist
- [ ] GitHub repository updated hai
- [ ] `.env` file gitignored hai
- [ ] Environment variables ready hain (BOT_TOKEN, ADMIN_ID)
- [ ] Bot token valid hai
- [ ] Bot ko channels mein admin banaya hai

## 🎯 Done!
Bas ab bot 24/7 live rahega Render pe! 🚀
