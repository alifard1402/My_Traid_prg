//+------------------------------------------------------------------+
//|                                        GoldPilotRecovery.mq4     |
//|   Gold (XAUUSD) assistant for M5/M15:                            |
//|     - Trend (HTF EMA + swing structure)                          |
//|     - Support / resistance levels (clustered swing points)       |
//|     - Trendlines (unbroken lines through swing lows / highs)     |
//|     - Supply / demand zones (base + impulse)                     |
//|     - Entry signals with alerts                                  |
//|     - Basket manager: +$ take profit, recovery trades every -$,  |
//|       basket target = ratio x worst drawdown, emergency stop     |
//+------------------------------------------------------------------+
#property strict
#property version   "4.00"
#property description "GoldPilot Recovery v4 - S/R, trendlines, supply/demand signals + basket recovery manager"

enum ENUM_OPPOSITE_ACTION
{
   OPPOSITE_CLOSE = 0,   // Close it (one direction only)
   OPPOSITE_ALERT = 1    // Alert only, manage as a separate basket
};

//==================================================================
//                    MONEY POLICY (BASKET)
//==================================================================
input string   s_money               = "=== Money policy (basket) ===";
input double   TakeProfitUSD         = 10.0;   // Min profit to close a single trade / basket
input double   StepLossUSD           = 10.0;   // Open next trade when the LAST trade is at -this
input double   RecoveryRatio         = 0.3333; // Basket target = ratio x worst basket drawdown
input int      MaxTrades             = 4;      // Max trades per basket (safety limit)
input double   MaxBasketLossUSD      = 100.0;  // Emergency stop: close basket at -this (required)
input double   RecoveryLotMultiplier = 1.0;    // 1.0 = same lot. >1 is martingale (dangerous)
input bool     AutoOpenRecovery      = true;   // true = EA opens recovery trades, false = alert only
input bool     SetBrokerTPSL         = true;   // Write basket TP / emergency SL on server orders
input double   ModifyThresholdPrice  = 0.50;   // Min TP/SL change (in price, e.g. 0.50 = 50 cents) before re-sending
input int      ModifyMinSeconds      = 10;     // Min seconds between TP/SL updates
input int      PauseAfterStopMinutes = 60;     // No auto entries after an emergency stop

//==================================================================
//                           ORDERS
//==================================================================
input string   s_orders              = "=== Orders ===";
input int      MagicNumber           = 26091101;
input bool     ManageManualTrades    = true;   // Manage trades you open by hand (magic 0)
input double   DefaultLots           = 0.01;   // Lot for BUY/SELL buttons and auto signals
input double   MaxLotPerTrade        = 0.02;   // No EA order is ever bigger than this
input ENUM_OPPOSITE_ACTION OppositeTradeAction = OPPOSITE_CLOSE; // Trade opposite to the open basket
input bool     ConfirmButtons        = true;   // Ask before BUY / SELL / CLOSE ALL
input double   MaxSpreadPrice        = 0.80;   // Max spread in price (0.80 = 80 cents on gold)
input double   SlippagePrice         = 0.50;   // Max slippage in price
input int      MaxRetries            = 3;

//==================================================================
//                         ENTRY SIGNAL
//==================================================================
input string   s_signal              = "=== Entry signal ===";
input ENUM_TIMEFRAMES SignalTF       = PERIOD_M15; // Entry timeframe (M5 or M15)
input ENUM_TIMEFRAMES TrendTF        = PERIOD_H1;  // Higher timeframe trend filter
input int      MinConfluence         = 1;      // Min reasons: level / zone / trendline (1-3)
input bool     AutoTradeSignals      = true;   // Open first trade on signal automatically
input bool     UseSessionFilter      = false;  // Auto entries only inside session (server time)
input int      SessionStartHour      = 7;
input int      SessionEndHour        = 22;

//==================================================================
//                           ANALYSIS
//==================================================================
input string   s_analysis            = "=== Analysis ===";
input int      LookbackBars          = 300;
input int      SwingLeft             = 3;      // Bars before a swing high/low
input int      SwingRight            = 3;      // Bars after (confirmation delay)
input int      ATRPeriod             = 14;
input int      TrendFastEMA          = 50;
input int      TrendSlowEMA          = 200;
input double   LevelToleranceATR     = 0.5;    // Swings closer than this (x ATR) = same level
input double   NearATR               = 0.5;    // "Price is at the level" distance (x ATR)
input double   ImpulseATR            = 1.5;    // Min impulse candle size (x ATR)
input int      MaxBaseCandles        = 3;
input int      TrendlinePoints       = 6;      // Last N swings used for trendlines

//==================================================================
//                       VISUAL & ALERTS
//==================================================================
input string   s_visual              = "=== Visual & alerts ===";
input bool     ShowDashboard         = true;
input bool     DrawLevels            = true;
input bool     DrawTrendlines        = true;
input bool     DrawZones             = true;
input bool     DrawSignals           = true;
input int      MaxLevelsEachSide     = 3;
input int      MaxZonesEachSide      = 2;
input bool     EnableAlerts          = true;
input bool     EnablePush            = false;  // Send to MT4 mobile app (set MetaQuotes ID first)
input bool     EnableSound           = false;
input int      DashX                 = 10;
input int      DashY                 = 20;
input int      DashFontSize          = 9;
input color    ColorSupport          = clrDodgerBlue;
input color    ColorResistance       = clrOrangeRed;
input color    ColorDemand           = C'0,60,0';
input color    ColorSupply           = C'70,0,0';

//==================================================================
//                         CONSTANTS / TYPES
//==================================================================
#define PREFIX     "GPR_"
#define BTN_BUY    "GPR_btnBuy"
#define BTN_SELL   "GPR_btnSell"
#define BTN_CLOSE  "GPR_btnClose"

struct SwingPt
{
   int    shift;
   double price;
};

struct SRLevel
{
   double price;
   int    touches;
};

struct SDZone
{
   int    kind;       // +1 demand, -1 supply
   double top;
   double bottom;
   int    shift;      // impulse candle
   int    baseShift;  // oldest base candle
   int    tests;      // times price came back into the zone
};

struct TLine
{
   bool   valid;
   int    s1;         // older point (bigger shift)
   double p1;
   int    s2;         // newer point
   double p2;
   int    touches;
};

struct BasketInfo
{
   int      count;
   double   lots;
   double   sumLotsOpen;   // sum(lots * open price)
   double   fees;          // swap + commission
   double   profit;        // profit + swap + commission
   int      lastTicket;
   datetime lastTime;
   double   lastProfit;
   double   lastLots;
   double   lastOpen;
   double   lastFees;
};

//==================================================================
//                            GLOBALS
//==================================================================
double   gO[], gH[], gL[], gC[], gA[];   // closed-bar cache, index = shift
int      gN = 0;
SwingPt  gSwH[], gSwL[];
SRLevel  gLevels[];
SDZone   gZones[];
TLine    gTLUp, gTLDn;
int      gHTF = 0, gStruct = 0, gTrend = 0;
double   gATR = 0;

int      gSigSide = 0;
double   gSigEntry = 0, gSigInvalid = 0, gSigTarget = 0;
string   gSigReason = "";

datetime gLastBar = 0;
double   gWorst[2];
datetime gLastModify[2];
int      gLastModifyCount[2];
int      gAlertedTicket[2];
bool     gMaxAlerted[2];
datetime gLastOpenTry[2];
datetime gPauseUntil = 0;
bool     gOppAlerted = false;

//==================================================================
//                            UTILITY
//==================================================================
int    Idx(int type)  { return(type == OP_BUY ? 0 : 1); }
int    Dir(int type)  { return(type == OP_BUY ? 1 : -1); }
string Side(int type) { return(type == OP_BUY ? "BUY" : "SELL"); }
string Px(double p)   { return(DoubleToString(p, Digits)); }

string TFName(ENUM_TIMEFRAMES tf)
{
   int t = (tf == PERIOD_CURRENT) ? Period() : (int)tf;
   string s = EnumToString((ENUM_TIMEFRAMES)t);
   return(StringSubstr(s, 7));
}

string TrendName(int t)
{
   if(t > 0) return("UP");
   if(t < 0) return("DOWN");
   return("NEUTRAL");
}

double ValuePerPrice()
{
   double tv = MarketInfo(Symbol(), MODE_TICKVALUE);
   double ts = MarketInfo(Symbol(), MODE_TICKSIZE);
   if(ts <= 0) return(0);
   return(tv / ts);   // account money per 1.0 price move per 1 lot
}

double NormalizeLots(double lots)
{
   double step = MarketInfo(Symbol(), MODE_LOTSTEP);
   double mn   = MarketInfo(Symbol(), MODE_MINLOT);
   double mx   = MarketInfo(Symbol(), MODE_MAXLOT);
   if(step <= 0) step = 0.01;
   lots = MathFloor(lots / step + 1e-7) * step;
   lots = MathMax(mn, MathMin(mx, lots));
   int d = (int)MathMax(0, MathCeil(-MathLog10(step) - 1e-9));
   return(NormalizeDouble(lots, d));
}

int SlippagePoints()
{
   return((int)MathMax(1, MathRound(SlippagePrice / Point)));
}

bool SpreadOK()
{
   return(Ask - Bid <= MaxSpreadPrice + Point * 0.5);
}

bool InSession()
{
   if(!UseSessionFilter) return(true);
   int h = TimeHour(TimeCurrent());
   if(SessionStartHour == SessionEndHour) return(true);
   if(SessionStartHour < SessionEndHour)
      return(h >= SessionStartHour && h < SessionEndHour);
   return(h >= SessionStartHour || h < SessionEndHour);
}

bool IsManaged()
{
   if(OrderSymbol() != Symbol()) return(false);
   if(OrderMagicNumber() == MagicNumber) return(true);
   return(ManageManualTrades && OrderMagicNumber() == 0);
}

bool Retryable(int err)
{
   return(err == ERR_TRADE_CONTEXT_BUSY || err == ERR_SERVER_BUSY ||
          err == ERR_PRICE_CHANGED || err == ERR_REQUOTE ||
          err == ERR_OFF_QUOTES || err == ERR_BROKER_BUSY ||
          err == ERR_TRADE_TIMEOUT);
}

void Notify(string msg)
{
   Print(msg);
   if(IsTesting()) return;
   if(EnableAlerts) Alert(msg);
   if(EnablePush)   SendNotification(StringSubstr(msg, 0, 250));
   if(EnableSound)  PlaySound("alert.wav");
}

string WorstName(int idx)
{
   return(StringFormat("GPR_%s_%d_%s_worst", Symbol(), MagicNumber, idx == 0 ? "buy" : "sell"));
}

double LoadWorst(int idx)
{
   string n = WorstName(idx);
   if(GlobalVariableCheck(n)) return(GlobalVariableGet(n));
   return(0);
}

void SaveWorst(int idx)
{
   string n = WorstName(idx);
   if(gWorst[idx] == 0) { if(GlobalVariableCheck(n)) GlobalVariableDel(n); }
   else GlobalVariableSet(n, gWorst[idx]);
}

double Target(int idx)
{
   return(MathMax(TakeProfitUSD, RecoveryRatio * (-gWorst[idx])));
}

//==================================================================
//                          INIT / DEINIT
//==================================================================
int OnInit()
{
   if(TakeProfitUSD <= 0 || StepLossUSD <= 0 || MaxBasketLossUSD <= 0 || MaxTrades < 1 ||
      RecoveryRatio <= 0 || RecoveryRatio > 1 || RecoveryLotMultiplier <= 0 || DefaultLots <= 0 ||
      MaxLotPerTrade < DefaultLots)
   {
      Alert("GoldPilot Recovery: invalid money settings. TakeProfitUSD, StepLossUSD, ",
            "MaxBasketLossUSD, MaxTrades, lots must be > 0, RecoveryRatio in (0,1], MaxLotPerTrade >= DefaultLots.");
      return(INIT_PARAMETERS_INCORRECT);
   }

   double lossAtLastAdd = StepLossUSD * MaxTrades * (MaxTrades - 1) / 2.0;
   if(MaxBasketLossUSD <= lossAtLastAdd)
      Print("WARNING: MaxBasketLossUSD (", DoubleToString(MaxBasketLossUSD, 2),
            ") is reached before trade #", MaxTrades, " can open (basket is already at -",
            DoubleToString(lossAtLastAdd, 2), " then).");
   if(RecoveryLotMultiplier > 1.0)
      Print("WARNING: RecoveryLotMultiplier > 1 is a martingale - losses grow much faster.");
   if(SignalTF != PERIOD_M5 && SignalTF != PERIOD_M15 && SignalTF != PERIOD_CURRENT)
      Print("NOTE: this EA is designed for M5 / M15 entries.");

   for(int i = 0; i < 2; i++)
   {
      gWorst[i]           = LoadWorst(i);
      gLastModify[i]      = 0;
      gLastModifyCount[i] = -1;
      gAlertedTicket[i]   = 0;
      gMaxAlerted[i]      = false;
      gLastOpenTry[i]     = 0;
   }

   ObjectsDeleteAll(0, PREFIX);
   CreateButtons();
   EventSetTimer(1);

   RunAnalysis();
   DrawAnalysis();
   gLastBar = iTime(NULL, SignalTF, 1);
   UpdateDashboard();

   Print("GoldPilot Recovery v4 started on ", Symbol(), " ", TFName(SignalTF),
         " | $1 price move per 1 lot = ", DoubleToString(ValuePerPrice(), 2));
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PREFIX);
   ChartRedraw(0);
}

//==================================================================
//                             TICK
//==================================================================
void OnTick()
{
   datetime bar = iTime(NULL, SignalTF, 1);
   if(bar > 0 && bar != gLastBar)
   {
      gLastBar = bar;
      RunAnalysis();
      DrawAnalysis();
      if(gSigSide != 0) AnnounceSignal();
      if(AutoTradeSignals) TryAutoEntry();
   }

   EnforceOneDirection();
   ManageBasket(OP_BUY);
   ManageBasket(OP_SELL);

   // The timer does not run in the Strategy Tester.
   if(IsTesting() && IsVisualMode()) UpdateDashboard();
}

void OnTimer()
{
   UpdateDashboard();
}

//==================================================================
//                     ANALYSIS (closed candles)
//==================================================================
void RunAnalysis()
{
   gSigSide = 0;
   gSigReason = "";
   gTLUp.valid = false;
   gTLDn.valid = false;
   int avail = iBars(NULL, SignalTF) - ATRPeriod - 2;
   gN = (int)MathMin(LookbackBars, avail);
   if(gN < 50) { gTrend = 0; return; }

   ArrayResize(gO, gN + 1);
   ArrayResize(gH, gN + 1);
   ArrayResize(gL, gN + 1);
   ArrayResize(gC, gN + 1);
   ArrayResize(gA, gN + 1);
   for(int s = 0; s <= gN; s++)
   {
      gO[s] = iOpen(NULL, SignalTF, s);
      gH[s] = iHigh(NULL, SignalTF, s);
      gL[s] = iLow(NULL, SignalTF, s);
      gC[s] = iClose(NULL, SignalTF, s);
      gA[s] = iATR(NULL, SignalTF, ATRPeriod, s);
   }
   gATR = gA[1];

   FindSwings();
   FindLevels();
   FindTrendline(true, gTLUp);
   FindTrendline(false, gTLDn);
   FindZones();
   ComputeTrend();
   ComputeSignal();
}

//---------------------------- swings -------------------------------
void AddSwing(SwingPt &arr[], int s, double p)
{
   int n = ArraySize(arr);
   ArrayResize(arr, n + 1);
   arr[n].shift = s;
   arr[n].price = p;
}

// Oldest first. A swing needs SwingRight newer bars to be confirmed,
// so the last SwingRight bars never contain one (no look-ahead).
void FindSwings()
{
   ArrayResize(gSwH, 0);
   ArrayResize(gSwL, 0);
   int k;
   for(int s = gN - SwingLeft; s >= 1 + SwingRight; s--)
   {
      bool isHigh = true, isLow = true;
      for(k = 1; k <= SwingLeft; k++)
      {
         if(gH[s] <= gH[s + k]) isHigh = false;
         if(gL[s] >= gL[s + k]) isLow = false;
      }
      for(k = 1; k <= SwingRight; k++)
      {
         if(gH[s] <= gH[s - k]) isHigh = false;
         if(gL[s] >= gL[s - k]) isLow = false;
      }
      if(isHigh) AddSwing(gSwH, s, gH[s]);
      if(isLow)  AddSwing(gSwL, s, gL[s]);
   }
}

//------------------------ support / resistance ---------------------
void AddLevel(double price, int touches)
{
   int n = ArraySize(gLevels);
   ArrayResize(gLevels, n + 1);
   gLevels[n].price = price;
   gLevels[n].touches = touches;
}

// Cluster all swing prices: swings closer than tolerance form one level.
void FindLevels()
{
   ArrayResize(gLevels, 0);
   int nh = ArraySize(gSwH), nl = ArraySize(gSwL), total = nh + nl;
   if(total == 0 || gATR <= 0) return;

   double prices[];
   ArrayResize(prices, total);
   int i;
   for(i = 0; i < nh; i++) prices[i] = gSwH[i].price;
   for(i = 0; i < nl; i++) prices[nh + i] = gSwL[i].price;
   ArraySort(prices);

   double tol = gATR * LevelToleranceATR;
   double sum = prices[0];
   int cnt = 1;
   for(i = 1; i < total; i++)
   {
      if(prices[i] - sum / cnt <= tol) { sum += prices[i]; cnt++; }
      else { AddLevel(sum / cnt, cnt); sum = prices[i]; cnt = 1; }
   }
   AddLevel(sum / cnt, cnt);
}

// below=true: highest level <= ref (support). below=false: lowest level > ref (resistance).
int NearestLevel(double ref, bool below)
{
   int best = -1;
   for(int i = 0; i < ArraySize(gLevels); i++)
   {
      double p = gLevels[i].price;
      if(below && p <= ref && (best < 0 || p > gLevels[best].price)) best = i;
      if(!below && p > ref && (best < 0 || p < gLevels[best].price)) best = i;
   }
   return(best);
}

//---------------------------- trendlines ---------------------------
int    SwShift(bool up, int i) { return(up ? gSwL[i].shift : gSwH[i].shift); }
double SwPrice(bool up, int i) { return(up ? gSwL[i].price : gSwH[i].price); }

double TLValue(TLine &t, int s)
{
   return(t.p1 + (t.p2 - t.p1) / (t.s1 - t.s2) * (t.s1 - s));
}

// up=true: rising line through swing lows (support).
// up=false: falling line through swing highs (resistance).
// Valid only if no candle CLOSED beyond it since the first point.
void FindTrendline(bool up, TLine &best)
{
   best.valid = false;
   best.touches = 0;
   best.s1 = 0; best.s2 = 0; best.p1 = 0; best.p2 = 0;

   int n = up ? ArraySize(gSwL) : ArraySize(gSwH);
   if(n < 2 || gATR <= 0) return;
   int first = (int)MathMax(0, n - TrendlinePoints);
   double tol = gATR * LevelToleranceATR;

   for(int a = first; a < n - 1; a++)
   {
      for(int b = a + 1; b < n; b++)
      {
         int    s1 = SwShift(up, a), s2 = SwShift(up, b);
         double p1 = SwPrice(up, a), p2 = SwPrice(up, b);
         if(s1 <= s2) continue;
         if(up && p2 <= p1) continue;
         if(!up && p2 >= p1) continue;

         double slope = (p2 - p1) / (s1 - s2);
         bool broken = false;
         for(int s = s1; s >= 1; s--)
         {
            double lv = p1 + slope * (s1 - s);
            if(up && gC[s] < lv - tol)  { broken = true; break; }
            if(!up && gC[s] > lv + tol) { broken = true; break; }
         }
         if(broken) continue;

         int touches = 0;
         for(int j = 0; j < n; j++)
         {
            int sj = SwShift(up, j);
            if(sj > s1) continue;
            if(MathAbs(SwPrice(up, j) - (p1 + slope * (s1 - sj))) <= tol) touches++;
         }

         if(!best.valid || touches > best.touches || (touches == best.touches && s2 < best.s2))
         {
            best.valid = true;
            best.s1 = s1; best.p1 = p1;
            best.s2 = s2; best.p2 = p2;
            best.touches = touches;
         }
      }
   }
}

//------------------------- supply / demand -------------------------
bool IsImpulse(int s)
{
   double rng = gH[s] - gL[s];
   if(rng <= 0 || gA[s] <= 0) return(false);
   return(rng >= ImpulseATR * gA[s] && MathAbs(gC[s] - gO[s]) / rng >= 0.6);
}

bool IsBase(int s)
{
   double rng = gH[s] - gL[s];
   if(rng <= 0) return(true);
   return(MathAbs(gC[s] - gO[s]) / rng <= 0.5 || rng <= 0.7 * gA[s]);
}

// Base candles (indecision) followed by an impulse candle.
// Bullish impulse -> demand zone, bearish impulse -> supply zone.
// A zone is dropped once a candle closes through it.
void FindZones()
{
   ArrayResize(gZones, 0);
   for(int s = gN - MaxBaseCandles; s >= 1; s--)
   {
      if(!IsImpulse(s)) continue;

      int cnt = 0;
      double bTop = -DBL_MAX, bBot = DBL_MAX, bHigh = -DBL_MAX, bLow = DBL_MAX;
      for(int j = s + 1; j <= gN && cnt < MaxBaseCandles; j++)
      {
         if(IsImpulse(j) || !IsBase(j)) break;
         cnt++;
         bTop  = MathMax(bTop, MathMax(gO[j], gC[j]));
         bBot  = MathMin(bBot, MathMin(gO[j], gC[j]));
         bHigh = MathMax(bHigh, gH[j]);
         bLow  = MathMin(bLow, gL[j]);
      }
      if(cnt == 0) continue;

      int kind = 0;
      double top = 0, bottom = 0;
      if(gC[s] > gO[s])
      {
         kind = 1; top = bTop; bottom = bLow;
         if(gC[s] <= top) continue;
      }
      else
      {
         kind = -1; top = bHigh; bottom = bBot;
         if(gC[s] >= bottom) continue;
      }

      bool broken = false, inside = false;
      int tests = 0;
      for(int k = s - 1; k >= 1; k--)
      {
         if(kind == 1 && gC[k] < bottom) { broken = true; break; }
         if(kind == -1 && gC[k] > top)   { broken = true; break; }
         bool touch = (kind == 1) ? (gL[k] <= top) : (gH[k] >= bottom);
         if(touch && !inside) tests++;
         inside = touch;
      }
      if(broken) continue;

      int n = ArraySize(gZones);
      ArrayResize(gZones, n + 1);
      gZones[n].kind = kind;
      gZones[n].top = top;
      gZones[n].bottom = bottom;
      gZones[n].shift = s;
      gZones[n].baseShift = s + cnt;
      gZones[n].tests = tests;
   }
}

// Most recent zone of this kind that contains price (+/- pad), formed before bar 1.
int ZoneAt(int kind, double price, double pad)
{
   for(int i = ArraySize(gZones) - 1; i >= 0; i--)
   {
      if(gZones[i].kind != kind || gZones[i].shift <= 1) continue;
      if(price >= gZones[i].bottom - pad && price <= gZones[i].top + pad) return(i);
   }
   return(-1);
}

// Nearest zone of this kind below (demand) / above (supply) the price.
int NearestZone(int kind, double price)
{
   int best = -1;
   double bestDist = DBL_MAX;
   for(int i = 0; i < ArraySize(gZones); i++)
   {
      if(gZones[i].kind != kind) continue;
      double d = (kind == 1) ? price - gZones[i].top : gZones[i].bottom - price;
      if(d < 0) d = 0;   // price is inside the zone
      if(d < bestDist) { bestDist = d; best = i; }
   }
   return(best);
}

//------------------------------ trend ------------------------------
void ComputeTrend()
{
   double c  = iClose(NULL, TrendTF, 1);
   double f  = iMA(NULL, TrendTF, TrendFastEMA, 0, MODE_EMA, PRICE_CLOSE, 1);
   double sl = iMA(NULL, TrendTF, TrendSlowEMA, 0, MODE_EMA, PRICE_CLOSE, 1);
   gHTF = 0;
   if(c > f && f > sl) gHTF = 1;
   else if(c < f && f < sl) gHTF = -1;

   gStruct = 0;
   int nh = ArraySize(gSwH), nl = ArraySize(gSwL);
   if(nh >= 2 && nl >= 2)
   {
      bool hh = gSwH[nh - 1].price > gSwH[nh - 2].price;
      bool hl = gSwL[nl - 1].price > gSwL[nl - 2].price;
      bool lh = gSwH[nh - 1].price < gSwH[nh - 2].price;
      bool ll = gSwL[nl - 1].price < gSwL[nl - 2].price;
      if(hh && hl) gStruct = 1;
      else if(lh && ll) gStruct = -1;
   }

   // Trend only when the two views do not disagree.
   if(gHTF * gStruct < 0) gTrend = 0;
   else gTrend = (gStruct != 0) ? gStruct : gHTF;
}

//------------------------------ signal -----------------------------
// BUY : uptrend + closed bullish candle touching support / demand / up trendline.
// SELL: downtrend + closed bearish candle touching resistance / supply / down trendline.
void ComputeSignal()
{
   gSigSide = 0;
   gSigReason = "";
   if(gTrend == 0 || gATR <= 0) return;

   double nearDist = gATR * NearATR;
   double buf = gATR * 0.3;
   double o1 = gO[1], h1 = gH[1], l1 = gL[1], c1 = gC[1];
   string reasons = "";
   int count = 0;

   if(gTrend > 0)
   {
      if(c1 <= o1) return;
      double lowest = l1;
      int si = NearestLevel(c1, true);
      if(si >= 0 && gLevels[si].price >= l1 - nearDist)
      {
         count++;
         reasons += StringFormat("S %s x%d; ", Px(gLevels[si].price), gLevels[si].touches);
         lowest = MathMin(lowest, gLevels[si].price);
      }
      int zi = ZoneAt(1, l1, nearDist);
      if(zi >= 0)
      {
         count++;
         reasons += StringFormat("Demand %s-%s; ", Px(gZones[zi].bottom), Px(gZones[zi].top));
         lowest = MathMin(lowest, gZones[zi].bottom);
      }
      if(gTLUp.valid)
      {
         double v = TLValue(gTLUp, 1);
         if(MathAbs(l1 - v) <= nearDist)
         {
            count++;
            reasons += "TL up " + Px(v) + "; ";
            lowest = MathMin(lowest, v);
         }
      }
      if(count < MinConfluence || count == 0) return;
      gSigSide = 1;
      gSigEntry = c1;
      gSigInvalid = lowest - buf;
      int ri = NearestLevel(c1, false);
      gSigTarget = (ri >= 0) ? gLevels[ri].price : 0;
   }
   else
   {
      if(c1 >= o1) return;
      double highest = h1;
      int ri2 = NearestLevel(c1, false);
      if(ri2 >= 0 && gLevels[ri2].price <= h1 + nearDist)
      {
         count++;
         reasons += StringFormat("R %s x%d; ", Px(gLevels[ri2].price), gLevels[ri2].touches);
         highest = MathMax(highest, gLevels[ri2].price);
      }
      int zi2 = ZoneAt(-1, h1, nearDist);
      if(zi2 >= 0)
      {
         count++;
         reasons += StringFormat("Supply %s-%s; ", Px(gZones[zi2].bottom), Px(gZones[zi2].top));
         highest = MathMax(highest, gZones[zi2].top);
      }
      if(gTLDn.valid)
      {
         double v2 = TLValue(gTLDn, 1);
         if(MathAbs(h1 - v2) <= nearDist)
         {
            count++;
            reasons += "TL down " + Px(v2) + "; ";
            highest = MathMax(highest, v2);
         }
      }
      if(count < MinConfluence || count == 0) return;
      gSigSide = -1;
      gSigEntry = c1;
      gSigInvalid = highest + buf;
      int si2 = NearestLevel(c1, true);
      gSigTarget = (si2 >= 0) ? gLevels[si2].price : 0;
   }
   gSigReason = reasons;
}

void AnnounceSignal()
{
   string msg = StringFormat("GoldPilot %s %s %s signal @ %s | invalid %s | target %s | %s",
                             Symbol(), TFName(SignalTF), gSigSide > 0 ? "BUY" : "SELL",
                             Px(gSigEntry), Px(gSigInvalid),
                             gSigTarget > 0 ? Px(gSigTarget) : "-", gSigReason);
   Notify(msg);
   if(DrawSignals) DrawSignalArrow();
}

void TryAutoEntry()
{
   if(gSigSide == 0) return;
   if(TimeCurrent() < gPauseUntil) return;
   if(!InSession() || !SpreadOK()) return;

   BasketInfo b, s;
   ScanBasket(OP_BUY, b);
   ScanBasket(OP_SELL, s);
   if(b.count > 0 || s.count > 0) return;   // one basket at a time

   OpenMarket(gSigSide > 0 ? OP_BUY : OP_SELL, DefaultLots, "GPR signal");
}

//==================================================================
//                         BASKET MANAGER
//==================================================================
bool HasTrades(int type)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() == type && IsManaged()) return(true);
   }
   return(false);
}

// One direction only: the first open trade decides the direction.
// A trade in the other direction is closed (or only reported).
void EnforceOneDirection()
{
   int      firstType = -1, firstTicket = 0;
   datetime firstTime = 0;
   bool     hasBuy = false, hasSell = false;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      int type = OrderType();
      if((type != OP_BUY && type != OP_SELL) || !IsManaged()) continue;
      if(type == OP_BUY) hasBuy = true; else hasSell = true;
      if(firstType < 0 || OrderOpenTime() < firstTime ||
         (OrderOpenTime() == firstTime && OrderTicket() < firstTicket))
      {
         firstType = type;
         firstTime = OrderOpenTime();
         firstTicket = OrderTicket();
      }
   }

   if(!(hasBuy && hasSell)) { gOppAlerted = false; return; }

   int opposite = (firstType == OP_BUY) ? OP_SELL : OP_BUY;
   if(OppositeTradeAction == OPPOSITE_CLOSE)
   {
      int n = CloseBasket(opposite);
      Notify(StringFormat("%s: one direction only (%s basket open) - closed %d %s trade(s)",
                          Symbol(), Side(firstType), n, Side(opposite)));
   }
   else if(!gOppAlerted)
   {
      gOppAlerted = true;
      Notify(StringFormat("%s: both BUY and SELL baskets are open", Symbol()));
   }
}

void ScanBasket(int type, BasketInfo &b)
{
   b.count = 0; b.lots = 0; b.sumLotsOpen = 0; b.fees = 0; b.profit = 0;
   b.lastTicket = -1; b.lastTime = 0; b.lastProfit = 0; b.lastLots = 0;
   b.lastOpen = 0; b.lastFees = 0;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() != type || !IsManaged()) continue;

      double fee = OrderSwap() + OrderCommission();
      double pr  = OrderProfit() + fee;
      b.count++;
      b.lots        += OrderLots();
      b.sumLotsOpen += OrderLots() * OrderOpenPrice();
      b.fees        += fee;
      b.profit      += pr;

      if(OrderOpenTime() > b.lastTime ||
         (OrderOpenTime() == b.lastTime && OrderTicket() > b.lastTicket))
      {
         b.lastTime   = OrderOpenTime();
         b.lastTicket = OrderTicket();
         b.lastProfit = pr;
         b.lastLots   = OrderLots();
         b.lastOpen   = OrderOpenPrice();
         b.lastFees   = fee;
      }
   }
}

// Close-side price (Bid for buys, Ask for sells) at which the basket P/L equals `money`.
double PriceForMoney(int type, BasketInfo &b, double money)
{
   double vpp = ValuePerPrice();
   if(vpp <= 0 || b.lots <= 0) return(0);
   return((b.sumLotsOpen + Dir(type) * (money - b.fees) / vpp) / b.lots);
}

// Price at which the LAST trade reaches -StepLossUSD (next recovery trade).
double NextAddPrice(int type, BasketInfo &b)
{
   double vpp = ValuePerPrice();
   if(vpp <= 0 || b.lastLots <= 0) return(0);
   return(b.lastOpen + Dir(type) * (-StepLossUSD - b.lastFees) / (vpp * b.lastLots));
}

void ManageBasket(int type)
{
   int idx = Idx(type);
   BasketInfo b;
   ScanBasket(type, b);

   if(b.count == 0)
   {
      if(gWorst[idx] != 0) { gWorst[idx] = 0; SaveWorst(idx); }
      gAlertedTicket[idx]   = 0;
      gMaxAlerted[idx]      = false;
      gLastModifyCount[idx] = -1;
      return;
   }

   if(b.profit < gWorst[idx]) { gWorst[idx] = b.profit; SaveWorst(idx); }
   double target = Target(idx);

   // 1) Target reached -> close the whole basket.
   if(b.profit >= target)
   {
      int n = CloseBasket(type);
      Notify(StringFormat("%s %s basket closed at target: %+.2f (%d trades, worst %.2f)",
                          Symbol(), Side(type), b.profit, n, gWorst[idx]));
      return;
   }

   // 2) Emergency stop.
   if(b.profit <= -MaxBasketLossUSD)
   {
      int n2 = CloseBasket(type);
      gPauseUntil = TimeCurrent() + PauseAfterStopMinutes * 60;
      Notify(StringFormat("EMERGENCY STOP %s %s basket: %.2f (%d trades closed)",
                          Symbol(), Side(type), b.profit, n2));
      return;
   }

   // 3) Recovery: last trade reached -StepLossUSD -> add a trade in the same direction.
   if(b.lastProfit <= -StepLossUSD)
   {
      if(b.count < MaxTrades)
      {
         if(AutoOpenRecovery)
         {
            if(SpreadOK() && TimeCurrent() - gLastOpenTry[idx] >= 5)
            {
               gLastOpenTry[idx] = TimeCurrent();
               double lots = NormalizeLots(MathMin(b.lastLots * RecoveryLotMultiplier, MaxLotPerTrade));
               if(OpenMarket(type, lots, StringFormat("GPR rec %d", b.count + 1)))
               {
                  Notify(StringFormat("%s recovery %s #%d opened (%.2f lot). Basket P/L %.2f",
                                      Symbol(), Side(type), b.count + 1, lots, b.profit));
                  ScanBasket(type, b);
               }
            }
         }
         else if(gAlertedTicket[idx] != b.lastTicket)
         {
            gAlertedTicket[idx] = b.lastTicket;
            Notify(StringFormat("%s: open recovery %s #%d now (last trade at %.2f)",
                                Symbol(), Side(type), b.count + 1, b.lastProfit));
         }
      }
      else if(!gMaxAlerted[idx])
      {
         gMaxAlerted[idx] = true;
         Notify(StringFormat("%s %s basket: MaxTrades (%d) reached. Holding for target %.2f or stop -%.2f",
                             Symbol(), Side(type), MaxTrades, target, MaxBasketLossUSD));
      }
   }

   // 4) Keep TP / SL on the server in sync (protects the basket if MT4 disconnects).
   if(SetBrokerTPSL) SyncTPSL(type, b, target);
}

void SyncTPSL(int type, BasketInfo &b, double target)
{
   int idx = Idx(type);
   if(b.count == gLastModifyCount[idx] && TimeCurrent() - gLastModify[idx] < ModifyMinSeconds)
      return;

   double tp = NormalizeDouble(PriceForMoney(type, b, target), Digits);
   double sl = NormalizeDouble(PriceForMoney(type, b, -MaxBasketLossUSD), Digits);
   if(tp <= 0) return;
   if(sl < 0) sl = 0;

   RefreshRates();
   double minDist = (MathMax(MarketInfo(Symbol(), MODE_STOPLEVEL),
                             MarketInfo(Symbol(), MODE_FREEZELEVEL)) + 2) * Point;
   double thr = MathMax(ModifyThresholdPrice, Point * 0.5);
   bool changed = false;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() != type || !IsManaged()) continue;

      double curTP = OrderTakeProfit(), curSL = OrderStopLoss();
      double newTP = tp, newSL = sl;
      if(type == OP_BUY)
      {
         if(newTP - Bid < minDist) newTP = curTP;                 // too close: software will close
         if(newSL > 0 && Bid - newSL < minDist) newSL = curSL;
      }
      else
      {
         if(Ask - newTP < minDist) newTP = curTP;
         if(newSL > 0 && newSL - Ask < minDist) newSL = curSL;
      }

      bool chTP = MathAbs(newTP - curTP) > thr;
      bool chSL = MathAbs(newSL - curSL) > thr;
      if(!chTP && !chSL) continue;
      if(ModifyOrder(OrderTicket(), OrderOpenPrice(), newSL, newTP)) changed = true;
   }

   if(changed || gLastModifyCount[idx] != b.count)
   {
      gLastModify[idx] = TimeCurrent();
      gLastModifyCount[idx] = b.count;
   }
}

//==================================================================
//                       ORDER OPERATIONS
//==================================================================
bool OpenMarket(int type, double lots, string comment)
{
   if(!IsTradeAllowed())
   {
      Print("Trading not allowed (enable AutoTrading).");
      return(false);
   }
   lots = NormalizeLots(MathMin(lots, MaxLotPerTrade));

   ResetLastError();
   if(AccountFreeMarginCheck(Symbol(), type, lots) <= 0 || GetLastError() == ERR_NOT_ENOUGH_MONEY)
   {
      Print("Not enough free margin for ", DoubleToString(lots, 2), " lot ", Side(type));
      return(false);
   }

   for(int r = 0; r < MathMax(1, MaxRetries); r++)
   {
      RefreshRates();
      double price = (type == OP_BUY) ? Ask : Bid;
      ResetLastError();
      int t = OrderSend(Symbol(), type, lots, NormalizeDouble(price, Digits), SlippagePoints(), 0, 0,
                        comment, MagicNumber, 0, type == OP_BUY ? clrLime : clrRed);
      if(t > 0) return(true);
      int err = GetLastError();
      Print("OrderSend ", Side(type), " failed, error ", err);
      if(!Retryable(err)) break;
      Sleep(250);
   }
   return(false);
}

bool ModifyOrder(int ticket, double openPrice, double sl, double tp)
{
   for(int r = 0; r < MathMax(1, MaxRetries); r++)
   {
      ResetLastError();
      if(OrderModify(ticket, openPrice, sl, tp, 0, clrNONE)) return(true);
      int err = GetLastError();
      if(err == ERR_NO_RESULT) return(true);
      Print("OrderModify #", ticket, " failed, error ", err);
      if(!Retryable(err)) break;
      Sleep(200);
      RefreshRates();
   }
   return(false);
}

bool CloseOrder(int ticket)
{
   for(int r = 0; r < MathMax(1, MaxRetries); r++)
   {
      if(!OrderSelect(ticket, SELECT_BY_TICKET)) return(false);
      if(OrderCloseTime() > 0) return(true);
      RefreshRates();
      double price = (OrderType() == OP_BUY) ? MarketInfo(OrderSymbol(), MODE_BID)
                                              : MarketInfo(OrderSymbol(), MODE_ASK);
      ResetLastError();
      if(OrderClose(ticket, OrderLots(), NormalizeDouble(price, Digits), SlippagePoints(), clrNONE))
         return(true);
      int err = GetLastError();
      Print("OrderClose #", ticket, " failed, error ", err);
      if(!Retryable(err)) break;
      Sleep(250);
   }
   return(false);
}

int CloseBasket(int type)
{
   int closed = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() != type || !IsManaged()) continue;
      if(CloseOrder(OrderTicket())) closed++;
   }
   return(closed);
}

//==================================================================
//                            BUTTONS
//==================================================================
void CreateButton(string name, string text, int x, color bg)
{
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_LOWER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 40);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, 100);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, 30);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, clrGray);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
}

void CreateButtons()
{
   CreateButton(BTN_BUY,   "BUY",       10,  clrDarkGreen);
   CreateButton(BTN_SELL,  "SELL",      115, clrMaroon);
   CreateButton(BTN_CLOSE, "CLOSE ALL", 220, clrDimGray);
}

bool Confirm(string text)
{
   if(!ConfirmButtons) return(true);
   return(MessageBox(text, "GoldPilot Recovery", MB_YESNO | MB_ICONQUESTION) == IDYES);
}

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id != CHARTEVENT_OBJECT_CLICK) return;
   if(sparam != BTN_BUY && sparam != BTN_SELL && sparam != BTN_CLOSE) return;

   if(sparam != BTN_CLOSE && OppositeTradeAction == OPPOSITE_CLOSE &&
      HasTrades(sparam == BTN_BUY ? OP_SELL : OP_BUY))
   {
      Notify("One direction only: close the open basket before trading the other way.");
   }
   else if(sparam == BTN_BUY)
   {
      if(Confirm(StringFormat("BUY %.2f lot %s ?", DefaultLots, Symbol())))
         OpenMarket(OP_BUY, DefaultLots, "GPR button");
   }
   else if(sparam == BTN_SELL)
   {
      if(Confirm(StringFormat("SELL %.2f lot %s ?", DefaultLots, Symbol())))
         OpenMarket(OP_SELL, DefaultLots, "GPR button");
   }
   else if(Confirm("Close ALL managed " + Symbol() + " trades?"))
   {
      int n = CloseBasket(OP_BUY);
      n += CloseBasket(OP_SELL);
      Notify(StringFormat("CLOSE ALL: %d trades closed", n));
   }

   ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
   UpdateDashboard();
   ChartRedraw(0);
}

//==================================================================
//                            DRAWING
//==================================================================
void DrawHLine(string name, double price, color c, int style, int width, string text)
{
   ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

void DrawLevelSet(bool below)
{
   double lim = Bid;
   for(int k = 0; k < MaxLevelsEachSide; k++)
   {
      int i = NearestLevel(lim, below);
      if(i < 0) break;
      double p = gLevels[i].price;
      int t = gLevels[i].touches;
      DrawHLine(PREFIX + (below ? "LV_S" : "LV_R") + IntegerToString(k), p,
                below ? ColorSupport : ColorResistance,
                t >= 2 ? STYLE_SOLID : STYLE_DOT, t >= 3 ? 2 : 1,
                StringFormat("%s x%d", below ? "S" : "R", t));
      lim = below ? p - Point * 0.1 : p;
   }
}

void DrawAnalysis()
{
   ObjectsDeleteAll(0, PREFIX + "LV_");
   ObjectsDeleteAll(0, PREFIX + "ZN_");
   ObjectsDeleteAll(0, PREFIX + "TL_");
   if(gN < 50) return;

   if(DrawLevels)
   {
      DrawLevelSet(true);
      DrawLevelSet(false);
   }

   if(DrawZones)
   {
      datetime right = iTime(NULL, SignalTF, 0) + PeriodSeconds(SignalTF) * 10;
      int nd = 0, ns = 0;
      for(int i = ArraySize(gZones) - 1; i >= 0; i--)
      {
         bool dem = (gZones[i].kind == 1);
         if(dem && nd >= MaxZonesEachSide) continue;
         if(!dem && ns >= MaxZonesEachSide) continue;
         string name = PREFIX + "ZN_" + IntegerToString(i);
         ObjectCreate(0, name, OBJ_RECTANGLE, 0,
                      iTime(NULL, SignalTF, gZones[i].baseShift), gZones[i].top,
                      right, gZones[i].bottom);
         ObjectSetInteger(0, name, OBJPROP_COLOR, dem ? ColorDemand : ColorSupply);
         ObjectSetInteger(0, name, OBJPROP_BACK, true);
         ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
         ObjectSetString(0, name, OBJPROP_TEXT,
                         StringFormat("%s tests:%d", dem ? "Demand" : "Supply", gZones[i].tests));
         if(dem) nd++; else ns++;
      }
   }

   if(DrawTrendlines)
   {
      DrawTL(PREFIX + "TL_up", gTLUp, ColorSupport);
      DrawTL(PREFIX + "TL_dn", gTLDn, ColorResistance);
   }
   ChartRedraw(0);
}

void DrawTL(string name, TLine &t, color c)
{
   if(!t.valid) return;
   ObjectCreate(0, name, OBJ_TREND, 0,
                iTime(NULL, SignalTF, t.s1), t.p1, iTime(NULL, SignalTF, t.s2), t.p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, name, OBJPROP_TEXT, StringFormat("touches:%d", t.touches));
}

void DrawSignalArrow()
{
   datetime t = iTime(NULL, SignalTF, 1);
   string name = PREFIX + "SIG_" + IntegerToString((int)t);
   double p = (gSigSide > 0) ? gL[1] - gATR * 0.2 : gH[1] + gATR * 0.2;
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_ARROW, 0, t, p);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, gSigSide > 0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, gSigSide > 0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

//==================================================================
//                           DASHBOARD
//==================================================================
// MT4 labels hold at most 63 characters, so every row stays short.
void Row(int &y, string key, string text, color c)
{
   string name = PREFIX + "D_" + key;
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, DashX);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, DashFontSize);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   if(text == "") text = " ";   // an empty label would show "Label"
   ObjectSetString(0, name, OBJPROP_TEXT, StringSubstr(text, 0, 63));
   y += DashFontSize + 9;
}

color TrendColor(int t)
{
   if(t > 0) return(clrLime);
   if(t < 0) return(clrRed);
   return(clrGray);
}

void BasketRows(int &y, int type)
{
   int idx = Idx(type);
   string k = (type == OP_BUY) ? "b" : "s";
   BasketInfo b;
   ScanBasket(type, b);

   if(b.count == 0)
   {
      Row(y, k + "1", Side(type) + " basket: -", clrGray);
      Row(y, k + "2", " ", clrGray);
      Row(y, k + "3", " ", clrGray);
      return;
   }

   double worst = MathMin(gWorst[idx], b.profit);
   double target = MathMax(TakeProfitUSD, RecoveryRatio * (-worst));
   color c = (b.profit >= 0) ? clrLime : clrOrange;
   Row(y, k + "1", StringFormat("%s x%d %.2f lot  P/L %+.2f  worst %.2f",
                                Side(type), b.count, b.lots, b.profit, worst), c);

   string add = (b.count < MaxTrades) ? Px(NextAddPrice(type, b)) : "max";
   Row(y, k + "2", StringFormat("  TP %+.2f @%s  next add @%s",
                                target, Px(PriceForMoney(type, b, target)), add), clrSilver);
   Row(y, k + "3", StringFormat("  STOP -%.2f @%s",
                                MaxBasketLossUSD, Px(PriceForMoney(type, b, -MaxBasketLossUSD))),
       clrTomato);
}

void UpdateDashboard()
{
   if(!ShowDashboard) return;
   int y = DashY;
   string tf = TFName(SignalTF);

   Row(y, "title", "GoldPilot Recovery v4  " + Symbol() + " " + tf, clrGold);

   string trendTxt = (gTrend > 0) ? "BULLISH" : (gTrend < 0) ? "BEARISH" : "NEUTRAL - wait";
   Row(y, "trend", "Trend: " + trendTxt, TrendColor(gTrend));
   Row(y, "trend2", StringFormat(" %s EMA: %s | %s swings: %s", TFName(TrendTF), TrendName(gHTF),
                                 tf, gStruct > 0 ? "HH/HL" : gStruct < 0 ? "LH/LL" : "mixed"),
       clrSilver);
   Row(y, "atr", StringFormat("ATR %.2f | Spread %.2f", gATR, Ask - Bid),
       SpreadOK() ? clrSilver : clrOrange);

   int si = NearestLevel(Bid, true), ri = NearestLevel(Bid, false);
   Row(y, "sr", StringFormat("S %s | R %s",
                             si >= 0 ? Px(gLevels[si].price) + " x" + IntegerToString(gLevels[si].touches) : "-",
                             ri >= 0 ? Px(gLevels[ri].price) + " x" + IntegerToString(gLevels[ri].touches) : "-"),
       clrSilver);

   int dz = NearestZone(1, Bid), sz = NearestZone(-1, Bid);
   Row(y, "dz", dz >= 0 ? StringFormat("Demand %s-%s t%d", Px(gZones[dz].bottom), Px(gZones[dz].top), gZones[dz].tests)
                        : "Demand -", ColorSupport);
   Row(y, "sz", sz >= 0 ? StringFormat("Supply %s-%s t%d", Px(gZones[sz].bottom), Px(gZones[sz].top), gZones[sz].tests)
                        : "Supply -", ColorResistance);
   Row(y, "tl", StringFormat("TL up %s | TL down %s",
                             gTLUp.valid ? Px(TLValue(gTLUp, 0)) : "-",
                             gTLDn.valid ? Px(TLValue(gTLDn, 0)) : "-"), clrSilver);

   if(gSigSide != 0)
   {
      Row(y, "sig", StringFormat("SIGNAL %s @%s inv %s tgt %s", gSigSide > 0 ? "BUY" : "SELL",
                                 Px(gSigEntry), Px(gSigInvalid), gSigTarget > 0 ? Px(gSigTarget) : "-"),
          gSigSide > 0 ? clrLime : clrRed);
      Row(y, "sig2", gSigReason, clrSilver);
   }
   else
   {
      Row(y, "sig", "No signal on last closed candle", clrGray);
      Row(y, "sig2", " ", clrGray);
   }

   Row(y, "sep", "------------------------------------", clrDimGray);
   BasketRows(y, OP_BUY);
   BasketRows(y, OP_SELL);
   Row(y, "sep2", "------------------------------------", clrDimGray);

   double vpp = ValuePerPrice();
   double stepDist = (vpp > 0) ? StepLossUSD / (vpp * DefaultLots) : 0;
   Row(y, "step", StringFormat("$%.0f = %.2f price move @ %.2f lot", StepLossUSD, stepDist, DefaultLots),
       clrSilver);
   double bal = AccountBalance();
   double riskPct = (bal > 0) ? MaxBasketLossUSD / bal * 100 : 0;
   Row(y, "risk", StringFormat("Emergency stop = %.1f%% of balance", riskPct),
       riskPct > 20 ? clrRed : riskPct > 10 ? clrOrange : clrSilver);
   if(TimeCurrent() < gPauseUntil)
      Row(y, "pause", "Auto entries paused after emergency stop", clrOrange);
   else
      Row(y, "pause", " ", clrGray);

   ChartRedraw(0);
}
//+------------------------------------------------------------------+
