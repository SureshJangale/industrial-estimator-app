"""Fixed-geometry one-page quotation renderer based on the supplied Quote 73 pattern.

The visible frame and grid use the same A4-page coordinates as the reference.
Only reusable geometry / generic fixed words are embedded in source code; the
historic client, quotation number, company GSTIN, and price are never embedded.
No source customer PDF or paid drawing software is needed at runtime.

This is deliberately a SHORT FORM. Long or overflowed quotes must use the
multi-annexure format instead of being silently clipped or rescaled.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.colors import black

PAGE_W, PAGE_H = 595.2, 841.8
X_LEFT, X_RIGHT = 72.0, 461.86
X_ITEM, X_QTY, X_RATE, X_AMOUNT = 101.18, 307.01, 350.11, 401.83
Y_TOP, Y_HEADER, Y_BODY, Y_ITEMS_HEADER = 103.22, 161.66, 275.27, 292.61
Y_ITEMS_END, Y_GST1, Y_GST2, Y_TOTAL, Y_VALIDITY, Y_SIGN, Y_BOTTOM = (
    533.23, 541.87, 550.51, 559.18, 568.75, 585.82, 662.98)


class LayoutOverflow(ValueError):
    """Data cannot fit safely in the exact single-page pattern."""


def fmt_money(raw: object, pending='PENDING') -> str:
    s = str(raw or '').strip()
    if not s or any(x in s.upper() for x in ('PENDING', 'NOT FINAL', 'REVIEW')):
        return pending
    if any(x in s.upper() for x in ('EXCLUDED', 'EXTRA', 'INCLUDED', 'ACTUAL')):
        return 'At Actual' if 'ACTUAL' in s.upper() else s.strip()
    s = re.sub(r'(?i)^(INR|RS\.?|\u20b9)\s*', '', s).replace(',', '')
    try:
        number=f'{Decimal(s):.2f}'
        head,tail=number.split('.')
        if len(head)>3:
            front,last=head[:-3],head[-3:]
            groups=[]
            while len(front)>2:
                groups.append(front[-2:]);front=front[:-2]
            if front:groups.append(front)
            head=','.join(reversed(groups))+','+last
        return head+'.'+tail
    except (InvalidOperation, ValueError):
        return str(raw).strip()[:40]


def sfield(context: dict, key: str, empty='') -> str:
    s = str(context.get('scalars', {}).get(key, '') or '').strip()
    return empty if s.upper() in ('NOT SPECIFIED', 'NONE') else s


def _w(text: str, font='Times-Roman', size=7.0) -> float:
    return pdfmetrics.stringWidth(str(text), font, size)


def wrap_lines(text: object, width: float, font='Times-Roman', size=7.0,
               max_lines: int = 12) -> list[str]:
    lines = []
    for raw in str(text or '').replace('\r', '').split('\n'):
        if raw == '':
            lines.append('')
            continue
        line = ''
        for word in raw.split():
            proposal = (line + ' ' + word).strip()
            if _w(proposal, font, size) <= width:
                line = proposal
            else:
                if line:
                    lines.append(line)
                line = word
                if _w(line, font, size) > width:
                    raise LayoutOverflow(f'Text does not fit in the original Quote 73 column: {word[:60]}')
        if line:
            lines.append(line)
    if len(lines) > max_lines:
        raise LayoutOverflow('Too many lines for the original Quote 73 one-page form')
    return lines


def _text(c: Canvas, x: float, ytop: float, value: object, font='Times-Roman',
          size=7, align='left', max_width: float | None = None,
          min_size: float=5.3) -> None:
    """Draw at top-origin baseline location; optionally shrink within a safe bound."""
    v = str(value or '').replace('\n', ' ').strip()
    if not v:
        return
    if max_width is not None:
        if _w(v, font, size) > max_width:
            size = max(min_size, size * max_width / max(_w(v, font, size), 1))
        if _w(v, font, size) > max_width + 0.2:
            raise LayoutOverflow('Field too long for the exact Quote 73 layout: '+v[:55])
    c.setFillColor(black)
    c.setFont(font, size)
    py = PAGE_H - ytop
    if align == 'right':
        c.drawRightString(x, py, v)
    elif align == 'center':
        c.drawCentredString(x, py, v)
    else:
        c.drawString(x, py, v)


def _line(c: Canvas, x1, y1, x2, y2, thickness=0.48):
    c.setLineWidth(thickness)
    c.line(x1, PAGE_H-y1, x2, PAGE_H-y2)


def _currency(c: Canvas, x, top, amount, width, font='Times-Roman', size=6):
    """Reference uses the rupee glyph. Render its symbol as simple vector strokes.
    The rest is core-14 PDF text, so there are no font files to distribute.
    """
    raw=str(amount or '')
    if raw.upper() in ('AT ACTUAL', 'AT ACTUAL - EXTRA', 'EXCLUDED', 'INCLUDED', 'PENDING', 'PRICE PENDING') or raw.startswith('NOT FINAL'):
        _text(c,x+width/2,top,('At Actual' if 'ACTUAL' in raw.upper() else 'PENDING' if 'PENDING' in raw.upper() or raw.startswith('NOT FINAL') else raw),font,size,align='center',max_width=width-4)
        return
    num=fmt_money(raw)
    if not re.fullmatch(r'[\d,]+\.\d{2}',num):
        _text(c,x+width/2,top,num,font,size,align='center',max_width=width-4)
        return
    symbol_w=6
    text_w=_w(num,font,size)
    total_w=symbol_w+text_w
    if total_w>width-4:
        size=max(5.2,size*(width-4)/total_w)
        text_w=_w(num,font,size)
        symbol_w=size
        total_w=symbol_w+text_w
    start=x+(width-total_w)/2
    # Small rupee-like glyph, traced as strokes in vector PDF (no font dependency).
    py=PAGE_H-top
    z=size/6
    c.setLineWidth(0.55*z)
    c.line(start+0.25*z,py+3.7*z,start+4.8*z,py+3.7*z)
    c.line(start+0.25*z,py+2.55*z,start+4.8*z,py+2.55*z)
    c.line(start+1.15*z,py+4.15*z,start+3.1*z,py+4.15*z)
    c.line(start+3.1*z,py+4.15*z,start+3.7*z,py+2.0*z)
    c.line(start+3.7*z,py+2.0*z,start+1.15*z,py+1.55*z)
    c.line(start+1.15*z,py+1.55*z,start+4.0*z,py-1.25*z)
    _text(c,start+symbol_w,top,num,font,size)


def _write_frame(c: Canvas):
    # Page border, duplicate divider rules, original 5-column table geometry.
    for x in (X_LEFT,X_RIGHT):
        _line(c,x,Y_TOP,x,Y_BOTTOM)
    for y in (Y_TOP,Y_HEADER,Y_HEADER+1.08,Y_BODY-.54,Y_BODY+.54,Y_ITEMS_HEADER,
              Y_ITEMS_END,Y_GST1,Y_TOTAL,Y_VALIDITY-1.08,Y_VALIDITY,Y_SIGN,Y_BOTTOM):
        _line(c,X_LEFT,y,X_RIGHT,y)
    # The separator between CGST and SGST exists only in the right-hand
    # tax-summary section in the source, not across the full table width.
    _line(c,X_QTY,Y_GST2,X_RIGHT,Y_GST2)
    # For Quote 73 the grid columns are continuous through their original bands.
    for x,end in ((X_ITEM,Y_SIGN), (X_QTY,Y_VALIDITY-1.08),
                  (X_RATE,Y_TOTAL), (X_AMOUNT,Y_SIGN)):
        start=Y_BODY+.54
        _line(c,x,start,x,end)
    # Following original layout, tax labels span the description/qty columns.
    # Top/bottom of the footer separate the GSTIN/closing and signatory.
    _line(c,X_RATE,Y_SIGN,X_RATE,Y_BOTTOM)
    # Payment-subtotal rows flow inside the same frame; no extra grid marks.


def _price_lines(c: Canvas, context: dict):
    lines = context.get('price_lines', []) or []
    if len(lines)>16:
        raise LayoutOverflow("Quote 73's fixed one-page form can show at most 16 item rows; use a multi-page quotation format.")
    y=308.4
    for i,entry in enumerate(lines,1):
        text=str(entry.get('description') or '').strip()
        hsn=str(entry.get('tax_code') or '').strip()
        if hsn and hsn.upper() not in ('NOT SPECIFIED','PENDING REVIEW'):
            _text(c,102.5,y-8.2,'HSN CODE- '+hsn,'Times-Bold',6,max_width=202)
        elif i==1:
            _text(c,102.5,y-8.2,'HSN CODE-','Times-Bold',6)
        rowlines=wrap_lines(text,200,'Times-Bold',6.0,max_lines=22)
        needed=max(9.4*len(rowlines)+9.5,18)
        if y+needed>526:
            raise LayoutOverflow('Quotation has more work/supply detail than fits the exact single-page Quote 73 grid. Select the multi-page equipment template.')
        _text(c,86.9,y,str(entry.get('no') or i),'Times-Bold',6,align='center',max_width=27)
        for j,line in enumerate(rowlines):
            _text(c,102.5,y+j*8.8,line,'Times-Bold',6,max_width=201)
        qty=str(entry.get('qty_unit') or '').strip().split(' ',1)
        _text(c,328.6,y,qty[0] if qty else '',size=6,align='center',max_width=39)
        if len(qty)>1:_text(c,328.6,y+8.9,qty[1].upper(),size=6,align='center',max_width=39)
        _currency(c,X_RATE+0.5,y,str(entry.get('rate') or ''),X_AMOUNT-X_RATE-1)
        _currency(c,X_AMOUNT+0.5,y,str(entry.get('amount') or ''),X_RIGHT-X_AMOUNT-1)
        y+=needed+2


def render_quote73(context: dict, *, draft_indicator=True) -> bytes:
    """Emit the reference's exact A4 grid and one-page hierarchy with new data.

    Raises LayoutOverflow instead of silently truncating item descriptions.
    """
    out=BytesIO()
    c=Canvas(out,pagesize=(PAGE_W,PAGE_H),pageCompression=1,invariant=1)
    seller=sfield(context,'seller.name','COMPANY NAME PENDING')
    c.setTitle(seller+' - Customer Quotation')
    c.setAuthor(seller)
    _write_frame(c)
    center=(X_LEFT+X_RIGHT)/2
    _text(c,center,111.6,sfield(context,'seller.heading',''),align='center',size=7.2,max_width=260)
    _text(c,center,121.0,'QUOTATION','Times-Bold',7.7,align='center')
    _text(c,center,135.5,seller,size=12.1,align='center',max_width=340,min_size=8.0)
    _line(c,center-_w(seller,'Times-Roman',min(12.1,12.1*340/max(_w(seller,'Times-Roman',12.1),1)))/2,136,
          center+_w(seller,'Times-Roman',min(12.1,12.1*340/max(_w(seller,'Times-Roman',12.1),1)))/2,136,0.6)
    _text(c,center,144.0,'Office:- '+sfield(context,'seller.address',''),size=6,align='center',max_width=345)
    _text(c,center,152.0,'Works Add :- '+sfield(context,'seller.works_address',''),size=6,align='center',max_width=345)
    # Customer / reference block: same baseline and x positions as source.
    _text(c,102.5,171,'To,',size=7.2)
    # The original Quote 73 reference is right-aligned in the RIGHT-HAND customer block.
    # Preserve its measured x=390.9 right edge; do not reflow to the left with Word edits.
    _text(c,390.9,170.0,'Quot No.'+sfield(context,'quote.number','PENDING'),'Times-Bold',6,align='right',max_width=103)
    _text(c,388.7,180.0,'Dt.'+sfield(context,'quote.date',''),'Times-Bold',6,align='right',max_width=103)
    _text(c,102.5,180.7,sfield(context,'buyer.name','PENDING REVIEW'),'Times-Bold',7.7,max_width=236)
    address=sfield(context,'buyer.address','PENDING REVIEW')
    addr=wrap_lines(address,225,'Times-Bold',6.3,max_lines=2)
    for j,line in enumerate(addr):_text(c,102.5,189.8+j*9.2,line,'Times-Bold',6.3,max_width=234)
    title=sfield(context,'product.name','PENDING REVIEW')
    _text(c,102.5,208.4,'Sub: Quotation for '+title,'Times-Bold',6.6,max_width=241)
    attention=sfield(context,'buyer.attention','')
    attention_text='Kind Attendance:-'+(attention if attention else 'PENDING REVIEW')
    _text(c,102.5,217.8,attention_text,'Times-Bold',6.6,max_width=244)
    _line(c,102.5,218.18,102.5+min(_w(attention_text,'Times-Bold',6.6),244),218.18,0.38)
    _text(c,102.5,227.3,'Dear sir,',size=7.2)
    _text(c,97.6,237,'Thank you very much for the countesy extended to the undersigned',size=7.2,max_width=300)
    _text(c,102.5,246.1,'when visited your office regarding the above mention subject',size=7.2,max_width=280)
    _text(c,102.5,255.5,'we are pleased to submit our offer for your kind persual.',size=7.2,max_width=280)
    _text(c,102.5,273.9,'Work as follows :-',size=7.2)
    # Header cells.
    for x,name in ((86.9,'Sr.No.'),(204.1,'Particulars'),(328.5,'Qty'),
                   (376,'Rate per Qty'),(431.4,'Amt. (Rs. )')):
        _text(c,x,287.2,name,size=7.2,align='center')
    _price_lines(c,context)
    # Payment terms sit at the base of the unusually tall item area.
    _text(c,102.5,532,'Payment Terms:- '+sfield(context,'commercial.payment','PENDING REVIEW'),
          'Times-Bold',6,max_width=201)
    subtotal=fmt_money(sfield(context,'pricing.subtotal'))
    _text(c,458.5,541.0,subtotal,size=6,align='right',max_width=55)
    taxes=context.get('tax_lines') or []
    if len(taxes)>2:
        raise LayoutOverflow('The exact Quote 73 format has two tax rows. Use another quotation format for more than two taxes.')
    for idx,tax in enumerate(taxes):
        y=(549.9,558.6)[idx]
        _text(c,305.6,y,'ADD-'+str(tax.get('name','TAX')).upper(),'Times-Bold',6.6,align='right',max_width=110)
        rate=str(tax.get('rate','')).strip()
        _text(c,400.8,y,rate+('%' if rate not in ('','-') else ''),'Times-Bold',6.6,align='right',max_width=48)
        _text(c,458.5,y,fmt_money(tax.get('amount','')),size=6,align='right',max_width=55)
    _text(c,340.6,567.1,'TOTAL','Times-Bold',6.6,align='right')
    _text(c,458.5,567.1,fmt_money(sfield(context,'pricing.total')),'Times-Bold',6,align='right',max_width=55)
    validity=sfield(context,'commercial.validity','PENDING REVIEW')
    valtext=f'**The rates and amount is valid for next {validity} from quote date.'
    _text(c,102.5,576.8,valtext,'Times-Italic',6.6,max_width=345)
    _line(c,102.5,577.03,102.5+min(350,_w(valtext,'Times-Italic',6.6)),577.03,0.3)
    # Footer exactly follows the original two-column signatory box.
    _text(c,73.3,605.0,'OUR G.S.T IN.NO. '+sfield(context,'seller.gstin','PENDING'),'Times-Bold',7.7,max_width=262)
    sig_header='For '+seller+'.'
    sig_max=X_RIGHT-X_RATE-9.5  # signed portion must remain inside the right-hand box
    if _w(sig_header,'Times-Roman',7.2)<=sig_max:
        _text(c,438.2,594.7,sig_header,size=7.2,align='right',max_width=sig_max)
    else:
        # A longer seller name is allowed, but never spills across the
        # vertical boundary into the GSTIN area of the original form.
        _text(c,457.0,594.7,'For',size=7.2,align='right',max_width=sig_max)
        sig_lines=wrap_lines(seller+'.',sig_max,'Times-Roman',6.2,max_lines=2)
        for j,line in enumerate(sig_lines):
            _text(c,457.0,603.0+j*7.4,line,size=6.2,align='right',max_width=sig_max)
    _text(c,421.4,632.6,sfield(context,'seller.signature_title','Authorized Signatory'),
          size=7.2,align='right',max_width=85)
    _text(c,73.3,652.4,'Your early reply in this matter will be highly appreciated.','Times-Bold',6.6,max_width=275)
    _text(c,73.3,662.0,'Thanking you and assuring our best services all the times.','Times-Bold',6.6,max_width=275)
    status=sfield(context,'quote.status')
    if draft_indicator and status!='ISSUED':
        # Outside the framed original layout so the appearance within the frame is unchanged.
        label='DRAFT / SYNTHETIC PREVIEW - NOT FOR ISSUE' if context.get('is_synthetic') else 'DRAFT - NOT FOR ISSUE'
        _text(c,267.0,684,label,'Times-Bold',8,align='center')
    c.showPage();c.save()
    return out.getvalue()
