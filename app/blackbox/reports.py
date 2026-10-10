import json
from html import escape
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from ..config import RUNTIME

def generate_pdf(run):
 path=RUNTIME/'reports'/f"blackbox-{run['id']}.pdf"
 styles=getSampleStyleSheet()
 font=Path('C:/Windows/Fonts/arial.ttf')
 if font.exists():
  if 'StudioArial' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('StudioArial',str(font)))
  for s in styles.byName.values():s.fontName='StudioArial'
 styles['BodyText'].leading=15;styles['BodyText'].wordWrap='CJK'
 story=[]
 def paragraph(text,style='BodyText'):
  story.append(Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style]));story.append(Spacer(1,7))
 paragraph('AI Agent Studio — black-box evaluation','Title')
 paragraph('Run '+run['id']);paragraph(run['score_formula'])
 for note in run.get('setup_notes',[]):paragraph(note)
 for index,s in enumerate(run['summary']):
  paragraph(s['name']+f" — {s['score']:.1f}%",'Heading1');paragraph(s['verdict'])
  for c in s['categories']:paragraph(f"{c['name']}: {c['score']:.1f}% | {c['tested']}/{c['total']} tested | {c['not_tested']} Not tested")
  paragraph('Top risks','Heading2')
  for c in s['risks']:paragraph(f"{c['name']} ({c['score']:.1f}%): inspect the linked case evidence; resolve missing configuration before treating the score as behavior quality.")
  paragraph('Strengths on tested criteria','Heading2')
  for c in s['strengths']:paragraph(f"{c['name']}: {c['score']:.1f}%")
  if not s['strengths']:paragraph('No high-scoring tested categories established.')
  paragraph('Failing examples','Heading2')
  for ident in s['examples']:
   c=next(c for c in run['cases'] if c['id']==ident);r=c['results'][index]
   paragraph(c['id']+': '+r['reason'])
   for turn in r['transcript']:
    paragraph('Customer: '+turn['input']);paragraph('Bot: '+str(turn.get('output') or turn.get('error')))
 if run.get('comparison'):paragraph('Comparison: '+str(run['comparison'].get('winner') or 'No overall winner')+'. '+run['comparison']['reason'],'Heading2')
 paragraph('Limitations','Heading2')
 for line in run['limitations']:paragraph(line)
 story.append(PageBreak());paragraph('All case evidence','Heading1')
 for c in run['cases']:
  paragraph(c['id']+' — '+c['name'],'Heading2');paragraph('Expected: '+c['expected'])
  for i,r in enumerate(c['results']):
   paragraph(run['targets'][i]['name']+f": {r['score']:.1f}% | {r['status']} | "+r['reason'])
   for t in r['transcript']:
    paragraph('Customer: '+t['input']);paragraph('Bot: '+str(t.get('output') or t.get('error')))
  if c.get('evidence_sha256'):paragraph('Evidence digest: '+c['evidence_sha256'])
 SimpleDocTemplate(str(path),title='AI Agent Studio black-box report',leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=42).build(story)
 return path
