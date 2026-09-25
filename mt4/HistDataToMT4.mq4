//+------------------------------------------------------------------+
//|                                              HistDataToMT4.mq4   |
//|  Converts free M1 history (HistData.com or Dukascopy CSV) into   |
//|  MT4 History Center import files, shifted to broker server time: |
//|     <symbol>_M1.csv, _M5, _M15, _M30, _H1, _H4, _D1              |
//|                                                                  |
//|  1. Put the source CSV files in MQL4/Files                       |
//|  2. Run this script on the chart of the broker's gold symbol     |
//|  3. Tools > History Center > symbol > timeframe > Import         |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs
#property version     "1.01"
#property description "HistData / Dukascopy M1 CSV -> MT4 History Center import files (broker time)"

enum ENUM_SRC_TZ
{
   SRC_EST    = 0,   // HistData.com (EST, no daylight saving)
   SRC_UTC    = 1,   // Dukascopy (GMT/UTC)
   SRC_BROKER = 2    // Already in broker server time
};

input string      InputFiles            = "DAT_MT_XAUUSD_M1_2025.csv"; // Files in MQL4/Files, oldest first, ';' separated
input ENUM_SRC_TZ SourceTimeZone        = SRC_EST;
input int         BrokerGMTOffsetWinter = 2;     // Broker server GMT offset in winter
input bool        BrokerFollowsUSDST    = true;  // +1 hour during US summer time (most brokers: GMT+2 / GMT+3)

#define NTF 7
int      TFS[NTF] = {1, 5, 15, 30, 60, 240, 1440};

int      gOut[NTF];
datetime gT[NTF];
double   gO[NTF], gH[NTF], gL[NTF], gC[NTF], gV[NTF];
bool     gOn[NTF];
int      gBars[NTF];
int      gDigits;

string TFLabel(int m)
{
   switch(m)
   {
      case 1:    return("M1");
      case 5:    return("M5");
      case 15:   return("M15");
      case 30:   return("M30");
      case 60:   return("H1");
      case 240:  return("H4");
      case 1440: return("D1");
   }
   return(IntegerToString(m));
}

string Trim(string text)
{
   int a = 0, b = StringLen(text) - 1;
   while(a <= b && StringGetCharacter(text, a) <= ' ') a++;
   while(b >= a && StringGetCharacter(text, b) <= ' ') b--;
   if(b < a) return("");
   return(StringSubstr(text, a, b - a + 1));
}

//------------------------- time zones -------------------------------
datetime NthSunday(int year, int month, int n)
{
   datetime first = StringToTime(StringFormat("%04d.%02d.01", year, month));
   int add = (7 - TimeDayOfWeek(first)) % 7;          // days to the first Sunday
   return(first + (add + (n - 1) * 7) * 86400);
}

// US daylight saving: 2nd Sunday of March 07:00 UTC .. 1st Sunday of November 06:00 UTC
bool IsUSDST(datetime utc)
{
   int y = TimeYear(utc);
   datetime start = NthSunday(y, 3, 2) + 7 * 3600;
   datetime stop  = NthSunday(y, 11, 1) + 6 * 3600;
   return(utc >= start && utc < stop);
}

datetime ToBroker(datetime t)
{
   if(SourceTimeZone == SRC_BROKER) return(t);
   datetime utc = (SourceTimeZone == SRC_EST) ? t + 5 * 3600 : t;
   int offset = BrokerGMTOffsetWinter + ((BrokerFollowsUSDST && IsUSDST(utc)) ? 1 : 0);
   return(utc + offset * 3600);
}

//--------------------------- parsing --------------------------------
// Supported lines:
//   HistData MetaTrader : 2025.01.02,18:00,2623.050,2623.050,2622.320,2622.380,0
//   HistData ASCII      : 20250102 180000;2623.050;2623.050;2622.320;2622.380;0
//   Dukascopy CSV       : 02.01.2025 00:00:00.000,2623.05,2623.05,2622.32,2622.38,12.5
bool ParseLine(string line, datetime &t, double &o, double &h, double &l, double &c, double &v)
{
   string p[];
   int n;
   if(StringFind(line, ";") >= 0)
   {
      n = StringSplit(line, ';', p);
      if(n < 5) return(false);
      string d = Trim(p[0]);                       // 20250102 180000
      if(StringLen(d) < 15) return(false);
      t = StringToTime(StringSubstr(d, 0, 4) + "." + StringSubstr(d, 4, 2) + "." + StringSubstr(d, 6, 2) + " " +
                       StringSubstr(d, 9, 2) + ":" + StringSubstr(d, 11, 2) + ":" + StringSubstr(d, 13, 2));
      o = StringToDouble(p[1]); h = StringToDouble(p[2]); l = StringToDouble(p[3]); c = StringToDouble(p[4]);
      v = (n > 5) ? StringToDouble(p[5]) : 0;
   }
   else
   {
      n = StringSplit(line, ',', p);
      if(n < 5) return(false);
      string f0 = Trim(p[0]);
      if(StringLen(f0) == 10 && StringGetCharacter(f0, 4) == '.')        // 2025.01.02,18:00,...
      {
         if(n < 6) return(false);
         t = StringToTime(f0 + " " + Trim(p[1]));
         o = StringToDouble(p[2]); h = StringToDouble(p[3]); l = StringToDouble(p[4]); c = StringToDouble(p[5]);
         v = (n > 6) ? StringToDouble(p[6]) : 0;
      }
      else if(StringLen(f0) >= 19 && StringGetCharacter(f0, 2) == '.')   // 02.01.2025 00:00:00.000,...
      {
         t = StringToTime(StringSubstr(f0, 6, 4) + "." + StringSubstr(f0, 3, 2) + "." + StringSubstr(f0, 0, 2) +
                          " " + StringSubstr(f0, 11, 8));
         o = StringToDouble(p[1]); h = StringToDouble(p[2]); l = StringToDouble(p[3]); c = StringToDouble(p[4]);
         v = (n > 5) ? StringToDouble(p[5]) : 0;
      }
      else return(false);                          // header or unknown line
   }
   if(t <= 0 || o <= 0 || h <= 0 || l <= 0 || c <= 0) return(false);
   if(h < MathMax(o, c) || l > MathMin(o, c) || h < l) return(false);
   return(true);
}

//--------------------------- output ---------------------------------
void Flush(int k)
{
   if(!gOn[k]) return;
   FileWrite(gOut[k], TimeToString(gT[k], TIME_DATE), TimeToString(gT[k], TIME_MINUTES),
             DoubleToString(gO[k], gDigits), DoubleToString(gH[k], gDigits),
             DoubleToString(gL[k], gDigits), DoubleToString(gC[k], gDigits),
             IntegerToString((int)gV[k]));
   gBars[k]++;
   gOn[k] = false;
}

void AddM1(datetime t, double o, double h, double l, double c, double v)
{
   // HistData has volume 0. Every M1 bar gets at least 1 tick and the
   // higher timeframes get the SUM of their M1 bars; otherwise the Strategy
   // Tester reports "unmatched data error (volume limit ... exceeded)".
   v = MathMax(1, MathRound(v));
   o = NormalizeDouble(o, gDigits); h = NormalizeDouble(h, gDigits);
   l = NormalizeDouble(l, gDigits); c = NormalizeDouble(c, gDigits);
   for(int k = 0; k < NTF; k++)
   {
      int sec = TFS[k] * 60;
      datetime bt = (datetime)(t - (t % sec));      // bar open time in broker time
      if(gOn[k] && bt != gT[k]) Flush(k);
      if(!gOn[k])
      {
         gOn[k] = true;
         gT[k] = bt;
         gO[k] = o; gH[k] = h; gL[k] = l; gC[k] = c; gV[k] = v;
      }
      else
      {
         gH[k] = MathMax(gH[k], h);
         gL[k] = MathMin(gL[k], l);
         gC[k] = c;
         gV[k] += v;
      }
   }
}

//---------------------------- main ----------------------------------
void OnStart()
{
   gDigits = Digits;
   string sym = Symbol();
   int k;

   for(k = 0; k < NTF; k++)
   {
      gOn[k] = false;
      gBars[k] = 0;
      string name = sym + "_" + TFLabel(TFS[k]) + ".csv";
      gOut[k] = FileOpen(name, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
      if(gOut[k] == INVALID_HANDLE)
      {
         Alert("Cannot create MQL4/Files/", name, " error ", GetLastError());
         for(int j = 0; j < k; j++) FileClose(gOut[j]);
         return;
      }
   }

   string files[];
   int nf = StringSplit(InputFiles, ';', files);
   long lines = 0, used = 0, skippedOrder = 0;
   datetime lastT = 0, firstT = 0;

   for(int f = 0; f < nf && !IsStopped(); f++)
   {
      string fname = Trim(files[f]);
      if(fname == "") continue;
      int h = FileOpen(fname, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
      {
         Alert("Cannot open MQL4/Files/", fname, " error ", GetLastError());
         continue;
      }
      Print("Reading ", fname);

      while(!FileIsEnding(h) && !IsStopped())
      {
         string line = FileReadString(h);
         lines++;
         datetime t;
         double o, hi, lo, c, v;
         if(!ParseLine(line, t, o, hi, lo, c, v)) continue;

         t = ToBroker(t);
         if(t <= lastT) { skippedOrder++; continue; }   // files must be oldest first
         lastT = t;
         if(firstT == 0) firstT = t;

         AddM1(t, o, hi, lo, c, v);
         used++;
         if(used % 100000 == 0) Comment("HistDataToMT4: ", used, " M1 bars, at ", TimeToString(t));
      }
      FileClose(h);
   }

   string report = StringFormat("HistDataToMT4 done: %d lines read, %d M1 bars used (%s .. %s)",
                                (int)lines, (int)used, TimeToString(firstT), TimeToString(lastT));
   for(k = 0; k < NTF; k++)
   {
      Flush(k);
      FileClose(gOut[k]);
      report += StringFormat("\n  %s_%s.csv : %d bars", sym, TFLabel(TFS[k]), gBars[k]);
   }
   if(skippedOrder > 0)
      report += StringFormat("\n  WARNING: %d bars skipped because time went backwards - list files oldest first",
                             (int)skippedOrder);
   Comment("");
   Print(report);
   Alert(report);
}
//+------------------------------------------------------------------+
