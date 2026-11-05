"""Generate a wholly synthetic demo drawing: not an engineering-approved fabrication design."""
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
p=Path(__file__).resolve().parents[1]/'data'/'SYNTHETIC_PALLET_DEMO.pdf'
c=Canvas(str(p),pagesize=A4);W,H=A4
c.setStrokeColor(HexColor('#1f4258'));c.setLineWidth(1)
c.setFont('Helvetica-Bold',20);c.drawString(44,H-52,'SYNTHETIC STEEL FRAME PALLET')
c.setFont('Helvetica',10);c.drawString(44,H-70,'Training fixture only  |  NOT A FABRICATION DRAWING')
c.rect(45,H-370,500,240)
c.setFont('Helvetica-Bold',12);c.drawString(58,H-150,'Technical requirements (synthetic)')
for i,line in enumerate(['Length: 1200 mm','Width: 600 mm','Height: 800 mm','Welded steel frame pallet','Material quantities: NOT PROVIDED','Steel grade: UNCONFIRMED','Finish colour: UNCONFIRMED']):
 c.setFont('Helvetica',11);c.drawString(58,H-178-i*25,line)
# Simplified non-scale overview graphic
c.setFont('Helvetica-Bold',12);c.drawString(45,H-415,'Non-scale illustrative frame outline')
c.setStrokeColor(HexColor('#087e75'));c.setLineWidth(3)
for x,y,w,h in [(78,H-615,320,132),(102,H-588,320,132)]:c.rect(x,y,w,h)
for x1,y1,x2,y2 in [(78,H-483,102,H-456),(398,H-483,422,H-456),(78,H-615,102,H-588),(398,H-615,422,H-588)]:c.line(x1,y1,x2,y2)
c.setFont('Helvetica',10);c.setFillColor(HexColor('#446171'));c.drawString(185,H-630,'Length: 1200 mm');c.drawString(427,H-520,'Width: 600 mm')
c.setFillColor(HexColor('#1f4258'));c.setFont('Helvetica-Bold',11);c.drawString(45,H-665,'Illustrative material legend (not a quantified BOM)')
c.setFont('Helvetica',10)
for i,line in enumerate(['SQ TUBE 40X40X3MM','MS FLAT 40X8MM','MS ANGLE 40X40X5MM','MS FLAT 25X3MM','MS MESH 1inchX 1inch','MS ANGLE 40X40X3MM','MS SHEET 1.6MM']):
 x=45 if i<4 else 300;y=H-686-(i if i<4 else i-4)*17
 c.drawString(x,y,line)
c.setFont('Helvetica-Oblique',8);c.setFillColor(HexColor('#ac4c4b'));c.drawString(45,45,'CAUTION: Synthetic exercise. Dimensions and sections are not a certified design.')
c.save();print('Generated',p)
