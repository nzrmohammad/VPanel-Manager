import io
import os
from reportlab.lib.pagesizes import A5
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.units import mm
import arabic_reshaper
from bidi.algorithm import get_display

def generate_receipt_pdf(user_name, amount, date_str, plan_name, tracking_id):
    """یک رسید PDF حرفه‌ای و گرافیکی تولید می‌کند."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A5)
    width, height = A5

    # --- 1. تنظیمات و لود فونت ---
    try:
        base_dir = os.path.dirname(__file__)
        font_path = os.path.join(base_dir, 'fonts', 'Vazir.ttf')
        # اگر فونت بولد هم دارید بهتر است لود کنید، فعلا از همان استفاده می‌کنیم
        pdfmetrics.registerFont(TTFont('Vazir', font_path))
        font_regular = 'Vazir'
        font_bold = 'Vazir' 
    except Exception as e:
        print(f"Font error: {e}")
        font_regular = 'Helvetica'
        font_bold = 'Helvetica-Bold'

    # --- توابع کمکی ---
    def draw_farsi(text, x, y, font_name, font_size, color=colors.black, align='center'):
        if font_regular == 'Vazir':
            reshaped_text = arabic_reshaper.reshape(str(text))
            bidi_text = get_display(reshaped_text)
        else:
            bidi_text = str(text)
        
        c.setFont(font_name, font_size)
        c.setFillColor(color)
        if align == 'center':
            c.drawCentredString(x, y, bidi_text)
        elif align == 'right':
            c.drawRightString(x, y, bidi_text)
        else:
            c.drawString(x, y, bidi_text)

    # --- 2. طراحی پس‌زمینه و کادر ---
    # رنگ پس‌زمینه خیلی کمرنگ برای زیبایی
    c.setFillColor(colors.whitesmoke)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    
    # کادر اصلی دور صفحه
    margin = 10 * mm
    c.setStrokeColor(colors.darkblue)
    c.setLineWidth(2)
    c.roundRect(margin, margin, width - 2*margin, height - 2*margin, 10, stroke=1, fill=0)

    # --- 3. هدر (Header) ---
    # نوار رنگی بالا
    header_height = 35 * mm
    c.setFillColor(colors.darkblue)
    # رسم مستطیل بالای کادر با گوشه‌های گرد بالا
    path = c.beginPath()
    path.moveTo(margin, height - margin - 10) # شروع از پایین انحنا
    path.lineTo(margin, height - margin - header_height) # پایین هدر
    path.lineTo(width - margin, height - margin - header_height) # راست پایین هدر
    path.lineTo(width - margin, height - margin - 10) # راست بالا
    # (ساده‌سازی شده: یک مستطیل رنگی می‌کشیم)
    c.rect(margin, height - margin - header_height, width - 2*margin, header_height, fill=1, stroke=0)
    
    # عنوان رسید
    draw_farsi("رسید پرداخت الکترونیکی", width/2, height - margin - 15*mm, font_bold, 20, colors.white)
    draw_farsi("VPanel Manager", width/2, height - margin - 25*mm, font_regular, 10, colors.lightgrey)

    # --- 4. اطلاعات اصلی (Body) ---
    current_y = height - margin - header_height - 20*mm
    row_height = 12 * mm
    
    # داده‌هایی که نمایش می‌دهیم
    data = [
        ("نام کاربر:", user_name),
        ("مبلغ پرداخت:", f"{amount:,.0f} تومان"),
        ("سرویس خریداری شده:", plan_name),
        ("تاریخ تراکنش:", date_str),
        ("شماره پیگیری:", str(tracking_id)),
        ("وضعیت:", "موفق ✅"),
        ("روش پرداخت:", "کیف پول")
    ]

    for label, value in data:
        # خط جداکننده کمرنگ
        c.setStrokeColor(colors.lightgrey)
        c.setLineWidth(0.5)
        c.line(margin + 10*mm, current_y - 3*mm, width - margin - 10*mm, current_y - 3*mm)
        
        # عنوان (راست)
        draw_farsi(label, width - margin - 15*mm, current_y, font_bold, 12, colors.darkslategrey, align='right')
        
        # مقدار (چپ)
        # اگر مبلغ است، رنگش را متمایز کنیم
        val_color = colors.black
        if "تومان" in value:
            val_color = colors.darkblue
        elif "موفق" in value:
            val_color = colors.green
            
        draw_farsi(value, margin + 15*mm, current_y, font_regular, 12, val_color, align='left')
        
        current_y -= row_height

    # --- 5. مهر حرفه‌ای (Stamp) ---
    # ذخیره وضعیت فعلی برای چرخش و تغییرات
    c.saveState()
    
    # تنظیم موقعیت مهر (پایین وسط یا سمت چپ)
    stamp_x = width / 2
    stamp_y = current_y - 10*mm
    c.translate(stamp_x, stamp_y)
    c.rotate(15) # چرخش 15 درجه
    
    # رنگ مهر (سبز یا قرمز)
    stamp_color = colors.Color(0, 0.5, 0, alpha=0.3) # سبز نیمه شفاف
    border_color = colors.Color(0, 0.5, 0, alpha=0.6)
    
    # دایره بیرونی
    c.setStrokeColor(border_color)
    c.setLineWidth(3)
    c.circle(0, 0, 35, stroke=1, fill=0)
    
    # دایره داخلی (نازک‌تر)
    c.setLineWidth(1)
    c.circle(0, 0, 30, stroke=1, fill=0)
    
    # متن وسط مهر
    if font_regular == 'Vazir':
        txt_main = get_display(arabic_reshaper.reshape("پرداخت شد"))
        txt_sub = "APPROVED"
    else:
        txt_main = "PAID"
        txt_sub = "OK"
        
    c.setFont(font_bold, 18)
    c.setFillColor(border_color)
    c.drawCentredString(0, 2, txt_main)
    
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(0, -10, txt_sub)
    
    # بازگرداندن تنظیمات بوم
    c.restoreState()

    # --- 6. فوتر (Footer) ---
    footer_y = margin + 10*mm
    draw_farsi("از اعتماد و خرید شما سپاسگزاریم", width/2, footer_y + 5*mm, font_regular, 10, colors.gray)
    
    # لینک پشتیبانی یا سایت (اگر دارید)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.blue)
    # c.drawCentredString(width/2, footer_y, "Support: @YourSupportID")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer