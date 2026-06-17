import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="EquityEdge Valuation Engine")

@app.get("/")
def home():
    return {"status": "EquityEdge Engine is Online & Healthy"}

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

    # calculator variables - can be set by user in future
    net_income_growth_target = 19
    market_cap_target = 10000000000
    peg_ratio_default = 99

    # Initialize evaluation flags and values safely outside the try block
    net_income_growth=0.0
    prior_3year_ni_growth=False
    yearly_revenue_increase=False
    revenue_growth=0.0

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
        peg_ratio = info.get('pegRatio', peg_ratio_default) # Default high if missing 
        current_ratio = info.get('currentRatio', 0)
        
        # Score calculation initialized
        total_score = 0
        
        # 1. Market Cap Criteria (Score = 1 if Large Cap > $10B) 
        if market_cap > market_cap_target:
            total_score += 1
            
        # 3 Net Income Check
        try:
            # 3.1. Safely lookup Net Income regardless of minor variation in yfinance index labels
            net_income_labels = ["Net Income", "Net Income From Continuing Operation Net Minority Interest"]
            net_income_series = None
            
            for label in net_income_labels:
                if label in financials.index:
                    net_income_series = financials.loc[label]
                    break

            # 3.2. Verify we found the metric and have at least 3 years of historical rows to evaluate
            if net_income_series is not None and len(net_income_series) >= 3:
                
                # yfinance annual DataFrames order headers from Newest to Oldest (Left to Right)
                current_fy_ni = net_income_series.iloc[0]       # Index 0 = Current FY
                last_year_ni  = net_income_series.iloc[1]       # Index 1 = Prior FY
                prior_year_ni = net_income_series.iloc[2]       # Index 2 = 2 Years Ago
                
                # 3.2.1. Simple Trend Check: Current FY Net Income > Last Year > Prior Year
                if current_fy_ni > last_year_ni and last_year_ni > prior_year_ni:
                    prior_3year_ni_growth = True

                # 3.2.2. Calculate YoY Net Income growth rate (using abs() for negative income recovery tracking)
                if last_year_ni != 0:
                    net_income_growth = ((current_fy_ni - last_year_ni) / abs(last_year_ni)) * 100
                
                # 3.2.3. Final metric scoring condition evaluation
                if prior_3year_ni_growth and net_income_growth > net_income_growth_target:
                    total_score += 1
                    
            else:
                # Instead of swallowing errors blindly, print or log meaningful diagnostic issues
                print("Skipping Net Income trend: Metric row missing or insufficient (3-year) column data.")

        except Exception as e:
            # Catch and log anomalies (e.g., unexpected data types or structures) without killing the app
            print(f"Error encountered during Net Income helper validation: {str(e)}")

        # 4 Extract Current and Prior FY Revenue safely
        try:
            if "Total Revenue" in financials.index:
                revenue_series = financials.loc["Total Revenue"]
                
                # yfinance columns are ordered chronologically backwards (Newest -> Oldest)
                current_fy_revenue = revenue_series.iloc[0]
                last_fy_revenue = revenue_series.iloc[1]
                prior_fy_revenue = revenue_series.iloc[2]
                
                if current_fy_revenue > last_fy_revenue > prior_fy_revenue: 
                    yearly_revenue_increase = True
                
                revenue_growth = ((current_fy_revenue - prior_fy_revenue) / prior_fy_revenue)*100

                if revenue_growth >= net_income_growth and yearly_revenue_increase:
                    total_score += 1
                
                # print(f"YoY Revenue Growth Rate: {revenue_growth}")
                
            else:
                print("Row item 'Total Revenue' not found in the financials statement.")
                
        except IndexError:
            print("Insufficient historical revenue data to retrieve both current and prior fiscal years.")

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
            conclusion = "UNDERVALUED"
        elif total_score >= 4:
            conclusion = "KEEP"
        else:
            conclusion = "OVERVALUED"
            
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
            "conclusion": conclusion,
            "3.ni_growth" : net_income_growth,
            "3.prior3yearNIgrowth" : prior_3year_ni_growth,
            "4. yearly_revenue_growth" : yearly_revenue_increase,
            "4.revenuegrowth" : revenue_growth
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis Engine Error: {str(e)}")