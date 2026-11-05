"""Editable customer-facing DOCX exports for the current quotation snapshot.

Word-backed formats retain their admin-authored Word layout. Other formats
produce a standards-based editable Word document containing the same public
quotation data. The Quote 73 PDF remains the fixed-position authoritative
visual match; Word rendering can vary between Microsoft Word and LibreOffice.
"""
from __future__ import annotations
from io import BytesIO
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _shade(cell, hexvalue='E9F1F6'):
    pr=cell._tc.get_or_add_tcPr();el=OxmlElement('w:shd');el.set(qn('w:fill'),hexvalue);pr.append(el)


def _text(doc, value='', bold=False):
    par=doc.add_paragraph()
    run=par.add_run(str(value or ''))
    run.bold=bold
    return par


def _add_table(doc, headings, rows, widths=None):
    table=doc.add_table(rows=1, cols=len(headings))
    table.style='Table Grid';table.alignment=WD_TABLE_ALIGNMENT.CENTER
    for i,value in enumerate(headings):
        cell=table.rows[0].cells[i];cell.text=str(value);_shade(cell)
        for run in cell.paragraphs[0].runs:run.bold=True
    for row in rows:
        cells=table.add_row().cells
        for i,value in enumerate(row):cells[i].text=str(value or '')
    if widths:
        for row in table.rows:
            for cell,width in zip(row.cells,widths):cell.width=Inches(width)
    for row in table.rows:
        for cell in row.cells:cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    return table


def _format_money(value):
    s=str(value or '')
    return s if s else 'Pending'


def generic_word(p, profile, state, *, firm=False, number=None) -> bytes:
    """Word fallback for declarative JSON quotation templates, never using internal cost/margins."""
    from .word_quote_templates import context_for
    context=context_for(p,profile,state,firm=firm,number=number)
    S=context['scalars'];T=profile.get('terms') or {}
    doc=Document()
    sec=doc.sections[0]
    sec.page_width=Inches(8.27);sec.page_height=Inches(11.69)
    sec.top_margin=Inches(.65);sec.bottom_margin=Inches(.65)
    sec.left_margin=Inches(.73);sec.right_margin=Inches(.73)
    normal=doc.styles['Normal'];normal.font.name='Arial';normal.font.size=Pt(9)
    normal.paragraph_format.space_after=Pt(4)
    hdr=doc.add_paragraph();hdr.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=hdr.add_run('COMPANY NAME PENDING' if S['seller.name']=='PENDING REVIEW' else S['seller.name']);r.bold=True;r.font.size=Pt(15);r.font.color.rgb=RGBColor(16,49,77)
    for key in ('seller.address','seller.works_address','seller.contact'):
        if S.get(key) and S[key]!='PENDING REVIEW':
            par=doc.add_paragraph(S[key]);par.alignment=WD_ALIGN_PARAGRAPH.CENTER
    title=doc.add_paragraph('QUOTATION');title.alignment=WD_ALIGN_PARAGRAPH.CENTER
    title.runs[0].bold=True;title.runs[0].font.size=Pt(13)
    ident=_add_table(doc,['To','Quotation No. / Date'],[
        [S['buyer.name'],'Quot No. '+S['quote.number']],
        [S['buyer.address'],'Dt. '+S['quote.date']],
        ['Kind Attendance: '+S['buyer.attention'],'']
    ],widths=[3.75,2.55])
    for row in ident.rows[1:]:
        row.cells[1].paragraphs[0].alignment=WD_ALIGN_PARAGRAPH.RIGHT
    _text(doc, 'Sub: Quotation for '+S['product.name'],bold=True)
    _text(doc, 'Dear sir,')
    _text(doc,'Thank you for your enquiry. We are pleased to submit our quotation for your consideration.')
    if T.get('scope'):
        _text(doc,'Scope: '+str(T['scope']))
    if profile.get('technical'):
        doc.add_heading('TECHNICAL SPECIFICATION',level=2)
        rows=[]
        for sec in profile['technical']:
            for field in sec.get('fields',[]):
                if field.get('value'):
                    rows.append([field.get('label') or field.get('key'),str(field['value'])+' '+str(field.get('unit') or '')])
        if rows:_add_table(doc,['Parameter','Specification'],rows)
    doc.add_heading('WORK AS FOLLOWS',level=2)
    prices=context['price_lines']
    _add_table(doc,['Sr.No.','Particulars','Qty','Rate per Qty (INR)','Amount (INR)'],[
        [x.get('no'),x.get('description'),x.get('qty_unit'),_format_money(x.get('rate')),_format_money(x.get('amount'))]
        for x in prices] or [['','No price lines entered','','','']])
    rows=[['Subtotal',S['pricing.subtotal']]]
    for tax in context['tax_lines']:
        rows.append([str(tax.get('name',''))+' '+str(tax.get('rate',''))+'%',tax.get('amount','PENDING')])
    rows.append(['TOTAL',S['pricing.total']])
    _add_table(doc,['Calculation','Amount'],rows)
    for key,label in [('commercial.payment','Payment terms'),('commercial.delivery','Delivery'),
                      ('commercial.validity','Quote validity'),('commercial.warranty','Warranty'),
                      ('commercial.inspection','Inspection'),('commercial.transport','Transport')]:
        if S.get(key) not in (None,'','PENDING REVIEW'):
            _text(doc,label+': '+S[key])
    _text(doc,'OUR G.S.T IN.NO. '+S['seller.gstin'])
    sig=doc.add_paragraph('For '+S['seller.name']+'\n\n'+S['seller.signature_title'])
    sig.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    if not firm:
        p=doc.add_paragraph('DRAFT - INTERNAL REVIEW ONLY; NOT FOR CUSTOMER ISSUE')
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    out=BytesIO();doc.save(out)
    return out.getvalue()


def export_word(p,profile,state,selected,db,*,firm=False,number=None) -> bytes:
    from .word_quote_templates import asset_for,context_for,render_word
    from .app import PRIVATE_DIR
    asset=asset_for(db,selected)
    if asset:
        source=(PRIVATE_DIR/asset.stored_name).read_bytes()
        context=context_for(p,profile,state,firm=firm,number=number,db=db)
        return render_word(source,context)
    return generic_word(p,profile,state,firm=firm,number=number)
