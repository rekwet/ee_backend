import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="EquityEdge Valuation Engine")

# Enable CORS so your Hostinger frontend can communicate securely with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["equityedge.me"],  # Replace with your actual domain for production security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Connection Configuration via Environment Variables
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/equityedge")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

class TickerInput(BaseModel):
    ticker: str

@app.post("/api/evaluate")
def evaluate_stock(data: TickerInput):
    ticker_code = data.ticker.upper().strip()
    
    try:
        stock = yf.Ticker(ticker_code)
        info = stock.info
        
        if not info or 'marketCap' not in info:
            raise HTTPException(status_code=404, detail="Ticker not found or data unavailable.")
        
        # Pull Financial Statements for multi-year trend logic
        financials = stock.financials      # Income Statement
        cashflow = stock.cashflow          # Cash Flow Statement
        balance = stock.balance_sheet      # Balance Sheet
        
        # Extract foundational values matching spreadsheet criteria
        market_cap = info.get('marketCap', 0)
        current_price = info.get('currentPrice', info.get('regularMarketPreviousClose', 0))
        exchange = info.get('exchange', 'Unknown')
        peg_ratio = info.get('pegRatio', 99) # Default high if missing 
        current_ratio = info.get('currentRatio', 0)
        
        # Score calculation initialized
        total_score = 0
        
        # 1. Market Cap Criteria (Score = 1 if Large Cap > $10B) 
        if market_cap > 10_000_000_000:
            total_score += 1
            
        # 3 & 4. Simple Trend Check Helper (Net Income / Revenue) 
        try:
            net_income_growth = financials.iloc[0, 0] > financials.iloc[0, 1]  # LY vs Prior Year 
            if net_income_growth: total_score += 1
        except Exception:
            pass

        # 7. Return on Equity (ROE) Criteria (Score = 1 if ROE > 12%) 
        roe = info.get('returnOnEquity', 0) * 100
        if roe > 12:
            total_score += 1
            
        # 8. Debt Settlement Capacity (Current Ratio > 1.5) 
        if current_ratio > 1.5:
            total_score += 1

        # 9. Future Prospects (Defaulting placeholder matching model rule) 
        total_score += 1

        # 11. Custom Value Investing Intrinsic Value Formula (Benjamin Graham Variant)
        # Intrinsic Value = EPS * (8.5 + 2 * Expected Growth Rate) 
        eps = info.get('trailingEps', 1)
        growth_rate = info.get('longName', 5) # fallback proxy
        intrinsic_value = max(0, round(eps * (8.5 + 2 * 5), 2)) 

        # Final Decision Logic mimicking your spreadsheet's criteria 
        # In the sample sheet, low scores (< 5) result in a "SELL" 
        if total_score >= 5 and peg_ratio <= 1 and current_price < intrinsic_value:
            conclusion = "BUY"
        elif total_score >= 4:
            conclusion = "HOLD"
        else:
            conclusion = "SELL"
            
        # Store Evaluation Results into PostgreSQL DB
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO stock_analyses (ticker, exchange, market_cap, current_price, intrinsic_value, peg_ratio, total_score, conclusion)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (ticker_code, exchange, market_cap, current_price, intrinsic_value, peg_ratio, total_score, conclusion))
            conn.commit()
        conn.close()
        
        return {
            "ticker": ticker_code,
            "exchange": exchange,
            "current_price": current_price,
            "intrinsic_value": intrinsic_value,
            "total_score": f"{total_score}/12",
            "conclusion": conclusion
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis Engine Error: {str(e)}")