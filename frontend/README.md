# frontend — React Web App

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in VITE_API_URL for production

# Start dev server (backend must be running on port 8000)
npm run dev
```

Open http://localhost:5173

## Build for production
```bash
npm run build    # outputs to dist/
```

## Folder structure

    src/
      App.jsx          ← Router, auth guard, sidebar, farm context
      main.jsx         ← React entry point
      index.css        ← Design tokens, global styles
      api/
        client.js      ← Axios instance + all API functions
      pages/
        Login.jsx      ← OTP authentication
        FarmSetup.jsx  ← Leaflet polygon draw (most complex page)
        Dashboard.jsx  ← Current status overview
        Forecast.jsx   ← 7-day SM + rain chart
        Decision.jsx   ← MPC decision + irrigation log
        Savings.jsx    ← Season savings vs blind baseline
      components/
        MetricCard.jsx ← Numeric metric display card
        DecisionCard.jsx ← MPC decision banner
        SMChart.jsx    ← Recharts SM + rain chart
        FarmMap.jsx    ← Leaflet farm polygon display
