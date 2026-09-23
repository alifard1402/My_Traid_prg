"""قضاوت ساده درباره نتیجه بک‌تست — برای کسی که اقتصاد نخوانده.

به جای اینکه فقط عدد نشان بدهیم، هر عدد را با یک معیار روشن می‌سنجیم و
یک جمله ساده می‌گوییم: خوب است، قابل قبول است، یا بد است — و چرا.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .metrics import Metrics


@dataclass
class Finding:
    level: str   # good | ok | bad
    title: str
    text: str


def gain(x: float) -> str:
    """۱۲.۳ → «۱۲.۳٪ سود» و -۵ → «۵.۰٪ ضرر»"""
    return f"{x:.1f}٪ سود" if x >= 0 else f"{-x:.1f}٪ ضرر"


def judge(m: Metrics, halves: tuple[Metrics, Metrics] | None = None) -> dict:
    """از روی معیارها یک خلاصه قابل فهم می‌سازد."""
    f: list[Finding] = []

    # ۱. تعداد معامله — بدون این، بقیه اعداد معنا ندارند
    if m.num_trades < 10:
        f.append(Finding("bad", "معامله خیلی کم",
            f"فقط {m.num_trades} معامله انجام شد. با این تعداد، نتیجه بیشتر شانس است تا مهارت. "
            "کندل‌های بیشتری (مثلاً ۳۰۰۰) یا تایم‌فریم کوتاه‌تری امتحان کن."))
    elif m.num_trades < 30:
        f.append(Finding("ok", "تعداد معامله کم",
            f"{m.num_trades} معامله. برای اطمینان آماری حداقل ۳۰ معامله لازم است؛ با احتیاط قضاوت کن."))
    else:
        f.append(Finding("good", "تعداد معامله کافی", f"{m.num_trades} معامله — برای قضاوت کافی است."))

    # ۲. سود کل
    if m.total_return_pct > 0:
        f.append(Finding("good", "سودده", f"در کل {m.total_return_pct:.1f}٪ سود کرد (بعد از کسر کارمزد)."))
    else:
        f.append(Finding("bad", "زیان‌ده", f"در کل {-m.total_return_pct:.1f}٪ ضرر کرد (بعد از کسر کارمزد)."))

    # ۳. مقایسه با «بخر و نگه دار» — مهم‌ترین مقایسه
    diff = m.total_return_pct - m.buy_hold_return_pct
    if diff >= 0:
        f.append(Finding("good", "بهتر از خرید ساده",
            f"اگر همان اول طلا می‌خریدی و نگه می‌داشتی {gain(m.buy_hold_return_pct)} می‌کردی؛ "
            f"ربات {diff:.1f} واحد درصد بهتر بود."))
    elif m.max_drawdown_pct > -15 and m.total_return_pct > 0:
        f.append(Finding("ok", "کمتر از خرید ساده، ولی کم‌ریسک‌تر",
            f"خرید و نگه‌داری {gain(m.buy_hold_return_pct)} داشت و ربات کمتر. ولی ربات فقط "
            f"{m.exposure_pct:.0f}٪ زمان در بازار بود و ریسک کمتری کشید."))
    else:
        f.append(Finding("bad", "بدتر از خرید ساده",
            f"اگر همان اول طلا می‌خریدی و نگه می‌داشتی {gain(m.buy_hold_return_pct)} می‌کردی. "
            "ربات با همه پیچیدگی‌اش از این بدتر بود."))

    # ۴. افت سرمایه — تحمل‌پذیری روانی
    dd = abs(m.max_drawdown_pct)
    if dd < 10:
        f.append(Finding("good", "افت سرمایه کم", f"بدترین افت از سقف فقط {dd:.1f}٪ بود."))
    elif dd < 25:
        f.append(Finding("ok", "افت سرمایه متوسط", f"در بدترین لحظه حساب {dd:.1f}٪ از سقفش پایین آمد."))
    else:
        f.append(Finding("bad", "افت سرمایه زیاد",
            f"در بدترین لحظه حساب {dd:.1f}٪ از سقفش پایین آمد. تحمل این در واقعیت خیلی سخت است."))

    # ۵. ضریب سوددهی
    pf = m.profit_factor
    if math.isinf(pf) or pf >= 1.5:
        f.append(Finding("good", "برد‌ها بزرگ‌تر از باخت‌ها",
            "مجموع سودها حداقل ۱.۵ برابر مجموع ضررها بود."))
    elif pf >= 1.0:
        f.append(Finding("ok", "برد و باخت نزدیک به هم",
            f"مجموع سودها فقط {pf:.2f} برابر مجموع ضررهاست. حاشیه امن کمی دارد."))
    elif m.num_trades:
        f.append(Finding("bad", "باخت‌ها بزرگ‌تر از بردها",
            f"مجموع سودها {pf:.2f} برابر مجموع ضررهاست (کمتر از ۱)."))

    # ۶. پایداری: آیا در هر دو نیمه داده کار کرده؟
    if halves:
        a, b = halves
        if a.total_return_pct > 0 and b.total_return_pct > 0:
            f.append(Finding("good", "پایدار در زمان",
                f"هم در نیمه اول ({a.total_return_pct:.1f}٪) و هم در نیمه دوم داده ({b.total_return_pct:.1f}٪) سودده بود."))
        elif a.total_return_pct > 0 or b.total_return_pct > 0:
            f.append(Finding("bad", "ناپایدار در زمان",
                f"نیمه اول {gain(a.total_return_pct)} و نیمه دوم {gain(b.total_return_pct)}. "
                "استراتژی‌ای که فقط در یک دوره کار کرده، احتمالاً شانسی بوده."))
        else:
            f.append(Finding("bad", "در هیچ دوره‌ای سودده نبود",
                f"نیمه اول {gain(a.total_return_pct)} و نیمه دوم {gain(b.total_return_pct)}."))

    score = sum({"good": 2, "ok": 1, "bad": 0}[x.level] for x in f) / (2 * len(f))
    if score >= 0.8:
        summary = ("good", "نتیجه امیدوارکننده است. قدم بعدی: همین تنظیمات را چند هفته در حالت کاغذی اجرا کن "
                           "و ببین در واقعیت هم همین‌طور است یا نه.")
    elif score >= 0.5:
        summary = ("ok", "نتیجه متوسط است. قبل از استفاده، روی بازه‌های دیگر (کندل بیشتر یا تایم‌فریم دیگر) هم تست کن.")
    else:
        summary = ("bad", "این تنظیمات را استفاده نکن. پارامترها یا استراتژی دیگری امتحان کن.")

    return {
        "level": summary[0],
        "summary": summary[1],
        "findings": [asdict(x) for x in f],
    }
