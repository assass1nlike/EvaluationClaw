"""Make an English print view of the actual review UI for browser PDF export."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]))
from evalclaw.reporting._katex_assets import inject_katex
from evalclaw.reporting.human_judge_template import HTML

TRANSLATIONS = {
    '人工评审 · 双题盲评':'Human review · blind A/B comparison',
    '题目质量比较':'Task quality comparison',
    '按需求契合度和评测质量综合选择':'Assess demand fit and evaluation quality',
    '用户测评需求':'User evaluation demand',
    '哪道题更好？':'Which task is better?',
    '请选择更适合评估上述用户需求的一道题。答案与作答仅作为判断题目质量的证据。':
        'Choose the task that better evaluates this demand. Use the recorded response as supporting evidence.',
    '理由（可选）':'Reason (optional)',
    '哪些具体内容影响了你的判断？':'What informed your comparison?',
    'A 更好':'Prefer A', 'B 更好':'Prefer B',
    '上一组':'Previous', '下一组':'Next', '提交并继续':'Submit and continue',
    '候选题目':'Candidate task', '题目内容（完整）':'Task',
    '模型作答（完整）':'Recorded model response', '附件与执行证据':'Files and execution evidence',
    '下载完整文件':'Download full file', '预览':'Preview',
    '大文件请下载查看；下载包含完整内容。':'Download for complete contents.',
    '展开完整内容':'Expand full record',
}


def main():
    html = HTML
    for original, translated in sorted(TRANSLATIONS.items(),key=lambda p:len(p[0]),reverse=True):
        html = html.replace(original,translated)
    html = html.replace('lang="zh-CN"','lang="en"')
    css = '''<style>
      body{font-size:20px;line-height:1.25;background:#f2f5f4}
      main{width:960px;max-width:none;padding:20px}
      header{margin-bottom:12px}h1{font-size:27px}h2{font-size:22px}h3{font-size:18px}
      .muted,#account{font-size:17px}.card{padding:16px;border-radius:7px}
      .requirement{margin-bottom:14px}.toolbar{margin-bottom:12px!important;gap:8px}
      .columns{gap:14px;align-items:stretch}.columns>.card{max-height:none;overflow:visible}
      .side-head{position:static;flex-wrap:wrap;gap:7px;padding-bottom:10px;margin-bottom:8px}
      .side-head h2{font-size:21px}.badge{padding:1px 10px}.task-kind{font-size:16px;color:#63777e;margin-left:auto}
      details{padding:9px 0}summary{font-size:18px}details>div{margin-top:8px}
      .artifact{font-size:17px;margin:6px 0;padding:7px}.artifact button{padding:2px 7px}
      section{margin-bottom:8px}.decision{margin-top:14px;padding:14px}
      .decision h2{font-size:22px}.decision p{font-size:17px;margin:6px 0}
      .choices{gap:12px;margin:9px 0}.choices label{padding:8px 12px}
      textarea{display:inline-block;width:calc(100% - 215px);vertical-align:middle;min-height:38px;height:38px;margin:0;font-size:17px}
      button{font-size:17px;padding:5px 9px}#vote>label{font-size:17px}
      #vote>label,#previous,#next,#review>.toolbar{display:none}
      #vote>.toolbar{display:inline-flex;vertical-align:middle;justify-content:flex-end;width:200px;margin:0!important}
      .illustration-note{font-size:16px;color:#63777e;margin:8px 0 0}
      #jump,#saved,#account,#progress{display:none!important}
      @media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}body{margin:0}}
    </style>'''
    html = html.replace('</head>',css+'</head>')
    output = HERE.parents[2]/'benchmark-output/paper-human-judge'
    output.mkdir(parents=True,exist_ok=True)
    (output/'interface.html').write_text(inject_katex(html))


if __name__=='__main__':
    main()
