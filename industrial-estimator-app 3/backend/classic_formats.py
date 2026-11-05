"""Classic quotation formats modeled on real multi-annexure industrial offers and one-page services.

All supplied content is escaped. Nothing in a template is executed as code. Original
customer documents are never bundled or embedded in these built-in formats.
"""
from __future__ import annotations
from datetime import date
import re
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, KeepTogether


def classic_quote(p, profile: dict, summary: dict, firm: bool = False, number=None, layout=None) -> bytes:
    layout = layout or {}
    style = layout.get('format_style', 'classic_equipment')
    if style not in ('classic_equipment', 'classic_service'):
        raise ValueError('Unknown classic quotation format')
    b = profile.get('branding') or {}
    terms = profile.get('terms') or {}
    pricing = summary['pricing']
    quote_no = number or profile.get('external_reference') or p.ref + ' / DRAFT'
    brand = str(b.get('name') or 'Your Company')
    placeholders={'{customer}':str(p.customer),'{project}':str(p.title),
                  '{quote_number}':str(quote_no),'{company_name}':brand,
                  '{date}':date.today().strftime('%d/%m/%Y')}
    def substitute(text):
        text=str(text or '')
        for key,value in placeholders.items():text=text.replace(key,value)
        return text
    primary = colors.HexColor(layout.get('primary_color', '#17344C'))
    accent = colors.HexColor(layout.get('accent_color', '#087E75'))
    light = colors.HexColor('#edf2f7')
    black = colors.HexColor('#20252c')
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=17*mm, rightMargin=17*mm,
                            topMargin=(13 if style=='classic_service' else 24)*mm, bottomMargin=(12 if style=='classic_service' else 19)*mm, title=str(b.get('name') or 'Customer Quotation')+' - Quotation')
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(name='CBrand', parent=ss['Normal'], fontName='Helvetica-Bold', fontSize=18,
                          leading=21, alignment=TA_CENTER, textColor=primary, spaceAfter=3))
    ss.add(ParagraphStyle(name='COver', parent=ss['Normal'], fontName='Helvetica-Bold', fontSize=10,
                          alignment=TA_CENTER, textColor=primary, leading=13))
    ss.add(ParagraphStyle(name='CMain', parent=ss['Normal'], fontName='Helvetica-Bold', fontSize=16,
                          leading=23, alignment=TA_CENTER, textColor=black))
    ss.add(ParagraphStyle(name='CAnnex', parent=ss['Normal'], fontName='Helvetica-Bold', fontSize=12,
                          leading=15, alignment=TA_CENTER, spaceAfter=12))
    ss.add(ParagraphStyle(name='CTitle', parent=ss['Normal'], fontName='Helvetica-Bold', fontSize=10,
                          leading=14, spaceBefore=12, spaceAfter=8))
    ss.add(ParagraphStyle(name='CText', parent=ss['Normal'], fontSize=9.3, leading=14, spaceAfter=6))
    ss.add(ParagraphStyle(name='CSmall', parent=ss['Normal'], fontSize=8.5, leading=12))
    ss.add(ParagraphStyle(name='CHeadCell', parent=ss['Normal'], fontName='Helvetica-Bold',
                          fontSize=8.1, leading=11))
    ss.add(ParagraphStyle(name='CCell', parent=ss['Normal'], fontSize=8.2, leading=11))
    ss.add(ParagraphStyle(name='CRight', parent=ss['Normal'], fontSize=9, leading=12,
                          alignment=TA_RIGHT))

    def txt(s):
        return escape(str(s or '')).replace('\n','<br/>')

    def para(s, typ='CText'):
        return Paragraph(txt(s), ss[typ])

    def rowtable(rows, widths, header=True, group_rows=()):
        t = Table([[para(c, 'CHeadCell' if header and i==0 else 'CCell') for c in row]
                   for i,row in enumerate(rows)], colWidths=widths, repeatRows=1 if header else 0,
                   hAlign='LEFT', splitByRow=1)
        commands=[('GRID',(0,0),(-1,-1),.45,colors.HexColor('#586675')),
                  ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                  ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
                  ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]
        if header: commands.append(('BACKGROUND',(0,0),(-1,0),light))
        for idx in group_rows:
            commands += [('SPAN',(0,idx),(-1,idx)),
                         ('BACKGROUND',(0,idx),(-1,idx),colors.HexColor('#f3f4f5'))]
        t.setStyle(TableStyle(commands))
        return t

    def company():
        a=[para(brand,'CBrand')]
        if b.get('address'):a.append(para(b['address'],'COver'))
        if b.get('contact'):a.append(para(b['contact'],'COver'))
        a.append(Spacer(1, 5*mm))
        return a

    def sign():
        return KeepTogether([Spacer(1, 13*mm),para('For ' + brand, 'CRight'),
                             Spacer(1, 8*mm),para(b.get('signature_title') or 'Authorized Signatory', 'CRight')])

    def priced_table(classic_service=False):
        headers=['No.','Particulars','Qty','Rate (INR)','Amount (INR)'] if classic_service else ['No.','Description','Qty / Unit','Rate (INR)','Amount (INR)']
        rows=[headers]
        for i,line in enumerate(pricing.get('lines',[]),1):
            mode=line.get('mode','')
            val = line.get('line_total')
            amount = (val if val is not None else {
                'AT_ACTUAL':'At actual / extra','INCLUDED':'Included','EXCLUDED':'Excluded',
                'NOTE':'Breakdown only'}.get(mode,'Pending'))
            if mode=='UNIT_RATE' and not line.get('qty'): amount='Quantity pending'
            description=line.get('description','')
            if line.get('notes'): description += '\n' + str(line['notes'])
            if line.get('tax_code'): description += '\nHSN/SAC: '+str(line['tax_code'])
            rows.append([str(i),description,
                         (str(line.get('qty') or '')+' '+str(line.get('unit') or '')).strip() if mode in ('FIXED','UNIT_RATE') else '',
                         str(line.get('price') or '') if mode in ('FIXED','UNIT_RATE') else '',str(amount)])
        if len(rows)==1:rows.append(['1','No line items entered','','',''])
        return rowtable(rows, [11*mm,85*mm,24*mm,27*mm,27*mm] if classic_service else [11*mm,79*mm,29*mm,27*mm,28*mm])

    def totals():
        st=[Spacer(1,5*mm),para('Known priced subtotal: INR '+str(pricing['subtotal_known']))]
        for tx in pricing.get('tax_components',[]):
            st.append(para(str(tx['name'])+' ('+str(tx['rate'])+'%): INR '+str(tx['amount'])))
        total_label='Total including tax' if pricing.get('grand_total_definitive') else 'Known priced items including tax'
        st.append(para(total_label + ': INR '+str(pricing['known_total_including_tax']),'CTitle'))
        if pricing.get('additional_at_actual'):
            st.append(para('Additional, not included: '+', '.join(pricing['additional_at_actual']),'CSmall'))
        if pricing.get('unpriced_lines'):
            st.append(para('Some price lines lack confirmed quantities or rates; this is not an all-inclusive quotation.','CSmall'))
        return st

    def terms_block():
        labels=[('scope','Scope of supply / work'),('payment','Payment terms'),('delivery','Delivery time'),
                ('warranty','Warranty'),('inspection','Inspection'),('transport','Transportation'),
                ('exclusions','Exclusions')]
        flow=[]
        for key,name in labels:
            if terms.get(key):
                flow.append(para(name,'CTitle'))
                flow.append(para(terms[key]))
        return flow

    def header(canvas, built):
        canvas.saveState()
        # Company letterhead is already present in the body at each annexure start.
        canvas.setFillColor(colors.grey);canvas.setFont('Helvetica',7.3)
        # Wrap long admin-customized footers instead of silently truncating words.
        footer = ' '.join(substitute(layout.get('footer') or 'Quotation '+str(quote_no)).split())
        usable = A4[0] - (17+17+29)*mm
        lines = ['']
        for word in footer.split(' '):
            trial = (lines[-1]+' '+word).strip()
            if lines[-1] and stringWidth(trial,'Helvetica',7.3)>usable:
                lines.append(word)
            else:
                lines[-1] = trial
        if len(lines)>2:
            lines=lines[:2]
            while stringWidth(lines[-1]+'...','Helvetica',7.3)>usable and lines[-1]:
                lines[-1]=lines[-1][:-1]
            lines[-1]+='...'
        for i,line in enumerate(lines):
            canvas.drawString(17*mm,(12+3.3*(len(lines)-i-1))*mm,line)
        canvas.drawRightString(A4[0]-17*mm,12*mm,'Page '+str(built.page))
        if not firm:
            canvas.translate(A4[0]/2,A4[1]/2);canvas.rotate(42)
            canvas.setFillColor(colors.Color(.7,.15,.15,alpha=.12))
            canvas.setFont('Helvetica-Bold',30);canvas.drawCentredString(0,0,'DRAFT - NOT FOR ISSUE')
        canvas.restoreState()

    flow=[]
    if style=='classic_service':
        flow+=company()
        flow.append(para(substitute(layout.get('title') or 'QUOTATION'),'CAnnex'))
        flow.append(para('Quotation No: '+str(quote_no)+'     Date: '+date.today().strftime('%d/%m/%Y'),'CTitle'))
        flow.append(para('To: '+str(p.customer)))
        flow.append(para('Kind Attendance: '+str(terms.get('customer_attention') or 'PENDING REVIEW')))
        flow.append(para('Subject: '+str(p.title)))
        flow.append(para(substitute(layout.get('intro') or 'We are pleased to submit our offer for your kind consideration.')))
        flow.append(para('Work as follows:', 'CTitle'))
        flow.append(priced_table(True))
        flow+=totals()
        flow+=terms_block()
        if layout.get('closing'):flow.append(para(substitute(layout['closing'])))
        flow.append(sign())
    else:
        # Page 1: title cover, as in the supplied technical-commercial examples.
        flow += company()
        flow.append(Spacer(1,45*mm))
        flow.append(para(substitute(layout.get('title') or 'TECHNO COMMERCIAL OFFER'), 'CMain'))
        flow.append(Spacer(1,5*mm))
        flow.append(para('FOR','CMain'))
        flow.append(Spacer(1,10*mm))
        flow.append(para(p.title.upper(), 'CMain'))
        flow.append(PageBreak())
        # Page 2: introduction and fully generated annexure index.
        flow += company()
        flow.append(para('QUOTATION NO: '+str(quote_no)+'     Date: '+date.today().strftime('%d/%m/%Y'),'CTitle'))
        flow.append(para('SUBJECT: TECHNO COMMERCIAL OFFER FOR '+str(p.title).upper(),'CTitle'))
        flow.append(para('To: '+str(p.customer)))
        flow.append(para('Kind Attendance: '+str(terms.get('customer_attention') or 'PENDING REVIEW')))
        flow.append(para('Dear Sir/Madam,'))
        flow.append(para(substitute(layout.get('intro') or 'We thank you for your enquiry and submit our technical and commercial offer for consideration.')))
        flow.append(Spacer(1,12*mm))
        flow.append(para('ANNEXURES','CTitle'))
        enabled={section['key']:section for section in layout.get('sections',[]) if section.get('enabled')}
        annex_order=[section['key'] for section in layout.get('sections',[])
                     if section.get('enabled') and section['key'] in ('technical','pricing','terms')]
        lettering={key:chr(ord('A')+i) for i,key in enumerate(annex_order)}
        def sec_heading(key):
            raw=enabled[key].get('title') or {'technical':'Technical specification',
                 'pricing':'Price schedule','terms':'Commercial terms and conditions'}[key]
            return re.sub(r'(?i)^ANNEXURE\s*[-:]?\s*[A-Z]\s*[-:]?\s*','',raw).strip().upper()
        for key in annex_order:
            flow.append(para('ANNEXURE - '+lettering[key]+'      '+sec_heading(key),'CTitle'))
        for key in annex_order:
            flow.append(PageBreak())
            flow+=company()
            flow.append(para('ANNEXURE - '+lettering[key]+'     '+sec_heading(key),'CAnnex'))
            if key=='technical':
                rows=[['ITEM','DESCRIPTION']]; groups=[]
                for section in profile.get('technical') or []:
                    groups.append(len(rows));rows.append([str(section.get('title') or 'GENERAL'),''])
                    for field in section.get('fields') or []:
                        if field.get('value'):
                            rows.append([str(field.get('label') or field.get('key')),
                                         str(field['value']) + (' '+str(field['unit']) if field.get('unit') else '')])
                if len(rows)==1:rows.append(['Technical scope','Requires engineering review'])
                flow.append(rowtable(rows,[62*mm,112*mm],group_rows=groups))
            elif key=='pricing':
                flow.append(priced_table())
                flow+=totals()
                if 'certifications' in enabled:
                    flow.append(Spacer(1,8*mm))
                    flow.append(para(enabled['certifications'].get('title') or 'CERTIFICATION / DOCUMENTS','CTitle'))
                    certs=terms.get('certifications') or []
                    if certs:
                        rows=[['No.','Certificate','Condition']]
                        for i,entry in enumerate(certs,1):
                            if isinstance(entry,dict):rows.append([str(i),str(entry.get('name','')),str(entry.get('condition',''))])
                            else:rows.append([str(i),str(entry),''])
                        flow.append(rowtable(rows,[13*mm,70*mm,91*mm]))
                    else:flow.append(para('No additional certificates listed.','CSmall'))
            elif key=='terms':
                flow += terms_block()
                if layout.get('closing'):flow.append(para(substitute(layout['closing'])))
                flow.append(sign())
    doc.build(flow,onFirstPage=header,onLaterPages=header)
    return buf.getvalue()
