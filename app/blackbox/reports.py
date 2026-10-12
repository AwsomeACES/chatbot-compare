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
  story.append(Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style]))
  spacer=Spacer(1,7);spacer.keepWithNext=style.startswith('Heading');story.append(spacer)
 paragraph('AI Agent Studio — black-box evaluation','Title')
 paragraph('Run '+run['id']);paragraph(run['score_formula'])
 for note in run.get('setup_notes',[]):paragraph(note)
 cost=run.get('costs',{})
 if cost.get('available'):
  from .cost_summary import money
  paragraph('Cost and token usage','Heading1');paragraph(cost['summary'])
  paragraph(cost['coverage_note'])
  paragraph('Pinned price snapshot: '+cost['snapshot_id']+'; model rates in USD per 1 million tokens: '+json.dumps(cost['prices_used']))
  for key in ('bot','evaluation'):
   total=cost[key]
   paragraph(key.title()+f": {total['input_tokens']} input / {total['output_tokens']} output tokens; cached input {total['cached_input_tokens']}; reasoning output {total['reasoning_tokens']}; local compute estimate "+money(total['local_compute_micro_usd'])+' (local API cost is zero). Unknown calls: '+str(total['unknown_calls']))
  paragraph('Manual INR/USD rate: '+str(cost['inr_per_usd'] or 'not configured')+'; qualifying score threshold: '+str(cost['score_threshold'])+'; cheapest qualifying slot: '+str(cost['cheapest_qualifying_slot'] or 'not established'))
  if cost['comparison_warning']:paragraph(cost['comparison_warning'])
  for bot in cost['bots']:
   paragraph(bot['name']+': target total '+money(bot['cost_micro_usd'])+'; per answer '+money(bot['cost_per_answer_micro_usd'])+'; per conversation '+money(bot['cost_per_conversation_micro_usd'])+'; per 1,000 '+money(bot['projected_1000_micro_usd']))
   paragraph(f"Tokens per answer: {bot['tokens_per_answer']}; tokens per conversation: {bot['tokens_per_conversation']}; mean latency ms: {bot['mean_latency_ms']}; quality per dollar: {bot['quality_per_dollar']}; measurement sources: "+', '.join(bot['token_sources']))
  for key,rows in cost['breakdowns'].items():
   paragraph('Cost by '+key.replace('_',' '),'Heading2')
   for row in rows:paragraph(str(row['name'])+': bot '+money(row['bot']['cost_micro_usd'])+'; evaluation '+money(row['evaluation']['cost_micro_usd'])+f"; tokens {row['input_tokens']} in / {row['output_tokens']} out; sources "+', '.join(row['token_sources']))
  paragraph('Retries: '+money(cost['retries']['cost_micro_usd'])+'; failed calls: '+money(cost['failed_calls']['cost_micro_usd'])+'. Included in totals; overlapping groups are not added again.')
  paragraph('Usage ledger (counts only)','Heading2')
  for event in cost['events']:
   paragraph(json.dumps(event,ensure_ascii=False))
 else:paragraph('Cost: Unknown. This historical run has no usage ledger.')

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
 def footer(canvas,doc):
  canvas.saveState();canvas.setFont('Helvetica',9);canvas.drawRightString(553,22,'Page '+str(doc.page));canvas.restoreState()
 SimpleDocTemplate(str(path),title='AI Agent Studio black-box report',leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=42).build(story,onFirstPage=footer,onLaterPages=footer)
 return path
